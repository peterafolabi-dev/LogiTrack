import logging
from urllib.parse import quote

from celery import shared_task
from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse
from django.utils import timezone
import requests

from .models import Business, DeliveryPreferenceRequest, Shipment, WebhookDeliveryLog
from .services.webhooks import deliver_webhook_sync

logger = logging.getLogger(__name__)

# Exponential backoff retry delays in seconds: 1m, 5m, 15m
RETRY_DELAYS = [60, 300, 900]


@shared_task(bind=True, max_retries=3)
def dispatch_webhook_task(self, business_id, event_type, payload, shipment_id=None):
    """
    Asynchronous webhook delivery task with exponential backoff retries (1m, 5m, 15m)
    and dead-letter logging upon repeated failure.
    """
    try:
        business = Business.objects.get(pk=business_id)
    except Business.DoesNotExist:
        logger.error("Business %s not found for webhook dispatch", business_id)
        return "Business not found"

    url = business.webhook_url
    if not url:
        return "No webhook URL configured"

    # Check if business subscribes to this event
    if business.webhook_events and event_type not in business.webhook_events:
        logger.debug("Event %s not in business %s subscription list", event_type, business_id)
        return "Event not subscribed"

    secret = business.webhook_secret
    attempt_num = self.request.retries + 1

    try:
        status_code, body = deliver_webhook_sync(url, secret, event_type, payload, timeout=10)
        if 200 <= status_code < 300:
            WebhookDeliveryLog.objects.create(
                business=business,
                shipment_id=shipment_id,
                event_type=event_type,
                target_url=url,
                payload=payload,
                status_code=status_code,
                response_body=body,
                status="success",
                attempts=attempt_num,
            )
            return f"Delivered {event_type} to {url} (HTTP {status_code})"
        else:
            raise requests.RequestException(f"Remote endpoint returned HTTP {status_code}: {body}")

    except Exception as exc:
        logger.warning(
            "Webhook attempt %d failed for business %s (%s): %s",
            attempt_num,
            business_id,
            url,
            exc,
        )
        if self.request.retries < len(RETRY_DELAYS):
            countdown = RETRY_DELAYS[self.request.retries]
            raise self.retry(exc=exc, countdown=countdown)
        else:
            WebhookDeliveryLog.objects.create(
                business=business,
                shipment_id=shipment_id,
                event_type=event_type,
                target_url=url,
                payload=payload,
                status_code=getattr(getattr(exc, "response", None), "status_code", None),
                response_body=str(exc)[:2000],
                status="dead_letter",
                attempts=attempt_num,
                error_message=f"Dead letter after {attempt_num} attempts: {exc}",
            )
            logger.error("Webhook dead-lettered for business %s (%s): %s", business_id, url, exc)
            return f"Dead-lettered after {attempt_num} attempts"


def queue_shipment_webhook(shipment_id: int, event_type: str):
    """
    Helper to serialize shipment state and schedule webhook dispatch task.
    """
    try:
        shipment = Shipment.objects.select_related("business").get(pk=shipment_id)
    except Shipment.DoesNotExist:
        return

    if not shipment.business or not shipment.business.webhook_url:
        return

    payload = {
        "event": event_type,
        "timestamp": timezone.now().isoformat(),
        "shipment": {
            "tracking_number": shipment.tracking_number,
            "status": shipment.status,
            "carrier": shipment.carrier,
            "origin": shipment.origin,
            "destination": shipment.destination,
            "estimated_delivery": shipment.estimated_delivery.isoformat() if shipment.estimated_delivery else None,
            "failure_reason": shipment.failure_reason,
            "updated_at": shipment.updated_at.isoformat(),
        },
    }

    dispatch_webhook_task.delay(
        shipment.business.id,
        event_type,
        payload,
        shipment_id=shipment.id,
    )


@shared_task(bind=True, max_retries=3)
def send_delivery_preference_invitation(self, request_id, token):
    try:
        preference_request = DeliveryPreferenceRequest.objects.select_related("shipment").get(pk=request_id)
    except DeliveryPreferenceRequest.DoesNotExist:
        return "Delivery preference request not found"

    if preference_request.sent_at:
        return "Invitation already sent"
    if preference_request.is_expired:
        return "Delivery preference link expired"

    shipment = preference_request.shipment
    path = reverse(
        "delivery_preferences",
        kwargs={"public_id": preference_request.public_id, "token": quote(token, safe="")},
    )
    url = f"{settings.PUBLIC_BASE_URL.rstrip('/')}{path}"
    subject = f"Delivery choices for shipment {shipment.tracking_number}"
    message = (
        f"Hello {shipment.recipient_name},\n\n"
        f"Shipment {shipment.tracking_number} is out for delivery. You can add drop-off instructions "
        f"or request another delivery date using this secure link:\n\n{url}\n\n"
        "This link expires in seven days. A date change is a request for the delivery team to review.\n"
    )

    try:
        send_mail(
            subject,
            message,
            settings.DEFAULT_FROM_EMAIL,
            [shipment.recipient_email],
            fail_silently=False,
        )
        preference_request.sent_at = timezone.now()
        preference_request.notification_error = ""
        preference_request.save(update_fields=["sent_at", "notification_error"])
        return "Invitation sent"
    except Exception as exc:
        preference_request.notification_error = str(exc)[:2000]
        preference_request.save(update_fields=["notification_error"])
        if self.request.retries < len(RETRY_DELAYS):
            raise self.retry(exc=exc, countdown=RETRY_DELAYS[self.request.retries])
        logger.exception("Delivery preference email exhausted retries for request %s", request_id)
        return "Invitation delivery failed"


def queue_delivery_preference_invitation(request_id, token):
    send_delivery_preference_invitation.delay(request_id, token)


@shared_task(bind=True, max_retries=3)
def validate_shipment_import_task(self, batch_id):
    from .services.shipment_imports import validate_shipment_import

    return validate_shipment_import(batch_id)


@shared_task(bind=True, max_retries=3)
def process_shipment_import_task(self, batch_id):
    from .services.shipment_imports import process_shipment_import

    return process_shipment_import(batch_id)

