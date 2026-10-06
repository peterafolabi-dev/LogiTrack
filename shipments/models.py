import secrets
import string

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.utils import timezone

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


class Profile(models.Model):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    business_name = models.CharField(max_length=120, blank=True, default="")
    timezone = models.CharField(max_length=64, default="UTC")
    distance_unit = models.CharField(max_length=12, default="miles")
    currency = models.CharField(max_length=3, default="USD")
    webhook_url = models.URLField(blank=True, default="")
    webhook_events = models.JSONField(default=list, blank=True)

    def __str__(self):
        return self.business_name or self.user.username


class Shipment(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="shipments")
    tracking_number = models.CharField(max_length=12, unique=True, db_index=True)
    recipient_name = models.CharField(max_length=120)
    recipient_phone = models.CharField(max_length=30)
    origin = models.CharField(max_length=160)
    destination = models.CharField(max_length=160)
    carrier = models.CharField(max_length=80, default="In-house fleet")
    estimated_delivery = models.DateTimeField(null=True, blank=True)
    description = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=STATUS_CHOICES, default="pending")
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.tracking_number} - {self.recipient_name}"

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
        if self.status not in dict(STATUS_CHOICES):
            raise ValidationError({"status": "Invalid status."})
        if self.status in {"delivered", "failed"}:
            return

    def save(self, *args, **kwargs):
        if not self.tracking_number:
            self.tracking_number = self.generate_unique_tracking_number()
        self.full_clean()
        return super().save(*args, **kwargs)

    def transition_to(self, status, location="", note=""):
        if self.status in {"delivered", "failed"}:
            raise ValidationError("This shipment is already finalized.")
        if not self.can_transition(self.status, status):
            raise ValidationError(f"Illegal status transition: {self.status} -> {status}")
        with transaction.atomic():
            self.status = status
            self.save(update_fields=["status", "updated_at"])
            StatusUpdate.objects.create(shipment=self, status=status, location=location, note=note)
        return self


class StatusUpdate(models.Model):
    shipment = models.ForeignKey(Shipment, on_delete=models.CASCADE, related_name="history")
    status = models.CharField(max_length=30, choices=STATUS_CHOICES)
    location = models.CharField(max_length=160, blank=True, default="")
    note = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["created_at"]

    def __str__(self):
        return f"{self.shipment.tracking_number} - {self.status}"

    def clean(self):
        super().clean()
        if not self.shipment.can_transition(self.shipment.status, self.status):
            raise ValidationError({"status": "Invalid status update for this shipment."})
