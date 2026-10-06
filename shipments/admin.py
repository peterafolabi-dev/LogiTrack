from django.contrib import admin

from .models import Business, Profile, Shipment, StatusUpdate, WebhookDeliveryLog


@admin.register(Business)
class BusinessAdmin(admin.ModelAdmin):
    list_display = ("name", "webhook_url", "created_at")
    search_fields = ("name", "webhook_url")


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "business", "business_name")
    search_fields = ("user__username", "user__email", "business_name")


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ("tracking_number", "business", "status", "recipient_name", "destination", "delivery_pin_raw", "created_at")
    list_filter = ("status", "carrier", "created_at")
    search_fields = ("tracking_number", "recipient_name", "destination")


@admin.register(StatusUpdate)
class StatusUpdateAdmin(admin.ModelAdmin):
    list_display = ("shipment", "status", "location", "failure_reason", "created_at")
    list_filter = ("status", "created_at")
    search_fields = ("shipment__tracking_number", "status", "location")


@admin.register(WebhookDeliveryLog)
class WebhookDeliveryLogAdmin(admin.ModelAdmin):
    list_display = ("event_type", "business", "status", "status_code", "attempts", "created_at")
    list_filter = ("status", "event_type", "created_at")
    search_fields = ("event_type", "target_url", "error_message")
