from django.db.models import Count, Q
from django.utils import timezone


PAGE_LABELS = {
    "landing": "Home",
    "login": "Log in",
    "signup": "Create account",
    "password_reset": "Reset password",
    "password_reset_done": "Check your email",
    "password_reset_confirm": "Choose a new password",
    "password_reset_complete": "Password updated",
    "dashboard": "Dashboard",
    "shipments_list": "Shipments",
    "shipment_create": "New shipment",
    "shipment_import_create": "Import shipments",
    "shipment_import_detail": "Import results",
    "shipment_detail": "Shipment details",
    "shipment_edit": "Edit shipment",
    "barcode_scanner": "Scanner",
    "profile": "Workspace settings",
    "public_tracking": "Track a shipment",
    "delivery_preferences": "Delivery preferences",
    "system_status": "System status",
}


def shared_navigation(request):
    label = PAGE_LABELS.get(getattr(getattr(request, "resolver_match", None), "url_name", ""), "LogiTrack")
    alert_counts = {"failed": 0, "due": 0, "total": 0}
    business_name = ""
    user = getattr(request, "user", None)
    if user and user.is_authenticated:
        business_id = getattr(getattr(user, "profile", None), "business_id", None)
        if business_id:
            from .models import Business, Shipment

            business_name = Business.objects.filter(pk=business_id).values_list("name", flat=True).first() or ""
            counts = Shipment.objects.filter(business_id=business_id).aggregate(
                failed=Count("id", filter=Q(status="failed")),
                due=Count(
                    "id",
                    filter=Q(
                        status__in=["pending", "picked_up", "in_transit", "out_for_delivery"],
                        sla_due_at__lt=timezone.now() + timezone.timedelta(hours=2),
                    ),
                ),
            )
            alert_counts = {"failed": counts["failed"], "due": counts["due"], "total": counts["failed"] + counts["due"]}
    return {"shared_page_label": label, "shared_alert_counts": alert_counts, "shared_business_name": business_name}
