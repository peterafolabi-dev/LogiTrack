import decimal
import hashlib
import secrets
import string
import uuid

from django.conf import settings
from django.contrib.auth.hashers import check_password, make_password
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

from .services.storage import get_presigned_url

STATUS_CHOICES = [
    ("pending", "Pending"),
    ("picked_up", "Picked Up"),
    ("in_transit", "In Transit"),
    ("out_for_delivery", "Out For Delivery"),
    ("delivered", "Delivered"),
    ("failed", "Failed"),
]

ALLOWED_TRANSITIONS = {
    "pending": {"picked_up", "failed"},
    "picked_up": {"in_transit", "failed"},
    "in_transit": {"out_for_delivery", "failed"},
    "out_for_delivery": {"delivered", "failed"},
    "delivered": set(),
    "failed": set(),
}

FAILURE_REASON_CHOICES = [
    ("customer_unavailable", "Customer Unavailable"),
    ("incorrect_address", "Incorrect Address"),
    ("gate_locked", "Gate / Access Code Required"),
    ("refused", "Delivery Refused by Recipient"),
    ("damaged_in_transit", "Package Damaged in Transit"),
    ("weather_delay", "Severe Weather / Road Blockage"),
    ("business_closed", "Business Closed"),
    ("other", "Other Delivery Exception"),
]


class Business(models.Model):
    """
    Multi-tenant enterprise boundary.
    All shipments, operations, metrics, and webhooks are scoped to a Business.
    """
    name = models.CharField(max_length=120)
    webhook_url = models.URLField(blank=True, default="")
    webhook_secret = models.CharField(max_length=64, blank=True)
    webhook_events = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name_plural = "Businesses"
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.webhook_secret:
            self.webhook_secret = secrets.token_hex(32)
        super().save(*args, **kwargs)


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="profiles", null=True, blank=True)
    business_name = models.CharField(max_length=120, blank=True, default="")
    timezone = models.CharField(max_length=64, default="UTC")
    distance_unit = models.CharField(max_length=12, default="miles")
    currency = models.CharField(max_length=3, default="USD")
    webhook_url = models.URLField(blank=True, default="")
    webhook_secret = models.CharField(max_length=64, blank=True)
    webhook_events = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.business_name or (self.business.name if self.business else self.user.username)

    def get_or_create_business(self):
        if not self.business_id:
            name = self.business_name.strip() or f"{self.user.username}'s Fleet"
            business, _ = Business.objects.get_or_create(
                name=name,
                defaults={
                    "webhook_url": self.webhook_url,
                    "webhook_events": self.webhook_events or [],
                    "webhook_secret": self.webhook_secret or secrets.token_hex(32),
                },
            )
            self.business = business
            if not self.business_name:
                self.business_name = name
            if not self.webhook_secret:
                self.webhook_secret = business.webhook_secret
            self.save(update_fields=["business", "business_name", "webhook_secret"])
        return self.business

    def save(self, *args, **kwargs):
        if not self.webhook_secret:
            self.webhook_secret = secrets.token_hex(32)
        super().save(*args, **kwargs)


class Shipment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shipments")
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="shipments", null=True, blank=True)
    tracking_number = models.CharField(max_length=12, unique=True, db_index=True)
    customer_reference = models.CharField(max_length=100, blank=True, default="")
    recipient_name = models.CharField(max_length=120)
    recipient_phone = models.CharField(max_length=30)
    recipient_email = models.EmailField(blank=True, default="")
    origin = models.CharField(max_length=160)
    destination = models.CharField(max_length=160)
    carrier = models.CharField(max_length=80, default="In-house fleet")
    estimated_delivery = models.DateTimeField(null=True, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="pending")

    # Electronic Proof of Delivery (ePoD) Assets & Telemetry
    recipient_signature = models.ImageField(upload_to="pod/signatures/%Y/%m/%d/", null=True, blank=True)
    delivery_photo = models.ImageField(upload_to="pod/photos/%Y/%m/%d/", null=True, blank=True)
    delivery_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    delivery_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    delivery_pin = models.CharField(max_length=128, blank=True)
    delivery_pin_raw = models.CharField(max_length=4, blank=True)
    failure_reason = models.CharField(max_length=40, choices=FAILURE_REASON_CHOICES, blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["business", "customer_reference"],
                condition=~models.Q(customer_reference=""),
                name="uniq_shipment_business_customer_reference",
            ),
        ]

    def __str__(self):
        return f"{self.tracking_number} - {self.recipient_name}"

    @property
    def signature_presigned_url(self):
        return get_presigned_url(self.recipient_signature)

    @property
    def photo_presigned_url(self):
        return get_presigned_url(self.delivery_photo)

    @staticmethod
    def generate_tracking_number():
        alphabet = "ABCDEFGHJKLMNPRSTUVWXYZ23456789"
        while True:
            candidate = "".join(secrets.choice(alphabet) for _ in range(10))
            if all(ch not in "0O1I L" for ch in candidate):
                return candidate

    @classmethod
    def generate_unique_tracking_number(cls):
        while True:
            candidate = cls.generate_tracking_number()
            if not cls.objects.filter(tracking_number=candidate).exists():
                return candidate

    def set_delivery_pin(self, raw_pin=None):
        if not raw_pin:
            raw_pin = f"{secrets.randbelow(10000):04d}"
        self.delivery_pin_raw = str(raw_pin)
        self.delivery_pin = make_password(str(raw_pin))
        return raw_pin

    def verify_delivery_pin(self, candidate_pin):
        if not self.delivery_pin:
            return True
        if not candidate_pin:
            return False
        candidate_pin = str(candidate_pin).strip()
        return check_password(candidate_pin, self.delivery_pin) or (self.delivery_pin_raw and candidate_pin == self.delivery_pin_raw)

    def can_transition(self, from_status, to_status):
        if not from_status or not to_status:
            return False
        if from_status == to_status:
            return False
        return to_status in ALLOWED_TRANSITIONS.get(from_status, set())

    def get_next_statuses(self):
        return sorted(ALLOWED_TRANSITIONS.get(self.status, set()))

    def clean(self):
        super().clean()
        if self.delivery_lat is not None:
            self.delivery_lat = round(decimal.Decimal(str(self.delivery_lat)), 6)
        if self.delivery_lng is not None:
            self.delivery_lng = round(decimal.Decimal(str(self.delivery_lng)), 6)
        if self.status not in dict(STATUS_CHOICES):
            raise ValidationError({"status": "Invalid status."})

    def save(self, *args, **kwargs):
        if not self.tracking_number:
            self.tracking_number = self.generate_unique_tracking_number()
        if not self.delivery_pin:
            self.set_delivery_pin()
        if not self.business_id and self.user_id:
            profile = getattr(self.user, "profile", None)
            if profile:
                self.business = profile.get_or_create_business()
        self.full_clean()
        return super().save(*args, **kwargs)

    def transition_to(
        self,
        status,
        location="",
        note="",
        recipient_signature=None,
        delivery_photo=None,
        delivery_lat=None,
        delivery_lng=None,
        delivery_pin=None,
        failure_reason="",
    ):
        if self.status in {"delivered", "failed"}:
            raise ValidationError("This shipment is already finalized.")
        if not self.can_transition(self.status, status):
            raise ValidationError(f"Illegal status transition: {self.status} -> {status}")

        if status == "delivered" and self.delivery_pin:
            if not self.verify_delivery_pin(delivery_pin):
                raise ValidationError("Invalid 4-digit delivery PIN.")

        if status == "failed" and not failure_reason:
            failure_reason = "other"

        if delivery_lat is not None:
            delivery_lat = round(decimal.Decimal(str(delivery_lat)), 6)
        if delivery_lng is not None:
            delivery_lng = round(decimal.Decimal(str(delivery_lng)), 6)

        delivery_request = None
        delivery_request_token = None
        with transaction.atomic():
            self.status = status
            update_fields = ["status", "updated_at"]

            if recipient_signature:
                self.recipient_signature = recipient_signature
                update_fields.append("recipient_signature")
            if delivery_photo:
                self.delivery_photo = delivery_photo
                update_fields.append("delivery_photo")
            if delivery_lat is not None:
                self.delivery_lat = delivery_lat
                update_fields.append("delivery_lat")
            if delivery_lng is not None:
                self.delivery_lng = delivery_lng
                update_fields.append("delivery_lng")
            if failure_reason:
                self.failure_reason = failure_reason
                update_fields.append("failure_reason")

            self.save(update_fields=update_fields)

            status_update = StatusUpdate.objects.create(
                shipment=self,
                status=status,
                location=location,
                note=note,
                recipient_signature=recipient_signature,
                delivery_photo=delivery_photo,
                delivery_lat=delivery_lat,
                delivery_lng=delivery_lng,
                delivery_pin=self.delivery_pin,
                failure_reason=failure_reason,
            )

            if status == "out_for_delivery" and self.recipient_email:
                delivery_request_token = secrets.token_urlsafe(32)
                delivery_request = DeliveryPreferenceRequest.objects.create(
                    shipment=self,
                    token_digest=hashlib.sha256(delivery_request_token.encode("utf-8")).hexdigest(),
                    expires_at=timezone.now() + timezone.timedelta(days=7),
                )

        # Trigger asynchronous webhook outside transaction
        from .tasks import queue_shipment_webhook
        transaction.on_commit(lambda: queue_shipment_webhook(self.pk, f"shipment.{status}"))
        if delivery_request:
            from .tasks import queue_delivery_preference_invitation

            transaction.on_commit(
                lambda: queue_delivery_preference_invitation(
                    delivery_request.pk,
                    delivery_request_token,
                )
            )

        return self


class DeliveryPreferenceRequest(models.Model):
    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    shipment = models.OneToOneField(
        Shipment,
        on_delete=models.CASCADE,
        related_name="delivery_preference_request",
    )
    token_digest = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    delivery_instructions = models.CharField(max_length=500, blank=True, default="")
    requested_delivery_date = models.DateField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    notification_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Delivery preferences for {self.shipment.tracking_number}"

    def matches_token(self, token):
        if not token or len(token) > 100:
            return False
        candidate_digest = hashlib.sha256(token.encode("utf-8")).hexdigest()
        return secrets.compare_digest(self.token_digest, candidate_digest)

    @property
    def is_expired(self):
        return timezone.now() >= self.expires_at


class ShipmentImportBatch(models.Model):
    STATUS_CHOICES = [
        ("queued", "Queued for validation"),
        ("validating", "Validating"),
        ("ready", "Ready to import"),
        ("processing", "Importing"),
        ("completed", "Completed"),
        ("completed_with_errors", "Completed with errors"),
        ("failed", "Failed"),
    ]

    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="shipment_imports")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shipment_imports")
    source_file = models.FileField(upload_to="shipment-imports/%Y/%m/")
    status = models.CharField(max_length=24, choices=STATUS_CHOICES, default="queued")
    total_rows = models.PositiveIntegerField(default=0)
    valid_rows = models.PositiveIntegerField(default=0)
    imported_rows = models.PositiveIntegerField(default=0)
    failed_rows = models.PositiveIntegerField(default=0)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"Import {self.pk} ({self.status}) for {self.business}"


class ShipmentImportRow(models.Model):
    STATUS_CHOICES = [
        ("pending", "Pending"),
        ("invalid", "Invalid"),
        ("imported", "Imported"),
        ("failed", "Failed"),
    ]

    import_batch = models.ForeignKey(ShipmentImportBatch, on_delete=models.CASCADE, related_name="rows")
    row_number = models.PositiveIntegerField()
    payload = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=STATUS_CHOICES, default="pending")
    error_message = models.CharField(max_length=500, blank=True, default="")
    shipment = models.ForeignKey(
        Shipment,
        on_delete=models.SET_NULL,
        related_name="import_rows",
        null=True,
        blank=True,
    )

    class Meta:
        ordering = ["row_number"]
        constraints = [
            models.UniqueConstraint(fields=["import_batch", "row_number"], name="uniq_import_batch_row_number"),
        ]

    def __str__(self):
        return f"Import {self.import_batch_id}, CSV row {self.row_number}"


class StatusUpdate(models.Model):
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name="history")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES)
    location = models.CharField(max_length=160, blank=True, default="")
    note = models.TextField(blank=True, default="")

    recipient_signature = models.ImageField(upload_to="pod/signatures/%Y/%m/%d/", null=True, blank=True)
    delivery_photo = models.ImageField(upload_to="pod/photos/%Y/%m/%d/", null=True, blank=True)
    delivery_lat = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    delivery_lng = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    delivery_pin = models.CharField(max_length=128, blank=True)
    failure_reason = models.CharField(max_length=40, choices=FAILURE_REASON_CHOICES, blank=True, default="")

    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.shipment.tracking_number} - {self.status}"

    def clean(self):
        super().clean()
        if self.delivery_lat is not None:
            self.delivery_lat = round(decimal.Decimal(str(self.delivery_lat)), 6)
        if self.delivery_lng is not None:
            self.delivery_lng = round(decimal.Decimal(str(self.delivery_lng)), 6)

    @property
    def signature_presigned_url(self):
        return get_presigned_url(self.recipient_signature)

    @property
    def photo_presigned_url(self):
        return get_presigned_url(self.delivery_photo)


class WebhookDeliveryLog(models.Model):
    business = models.ForeignKey(Business, on_delete=models.CASCADE, related_name="webhook_logs", null=True, blank=True)
    shipment = models.ForeignKey(Shipment, on_delete=models.SET_NULL, related_name="webhook_deliveries", null=True, blank=True)
    event_type = models.CharField(max_length=80)
    target_url = models.URLField()
    payload = models.JSONField(default=dict)
    status_code = models.IntegerField(null=True, blank=True)
    response_body = models.TextField(blank=True, default="")
    status = models.CharField(
        max_length=20,
        choices=[("success", "Success"), ("failed", "Failed"), ("dead_letter", "Dead Letter")],
        default="success",
    )
    attempts = models.PositiveIntegerField(default=1)
    error_message = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.event_type} -> {self.target_url} [{self.status}]"
