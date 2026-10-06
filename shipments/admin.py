from django.contrib import admin

from .models import Profile, Shipment, StatusUpdate


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "business_name")


@admin.register(Shipment)
class ShipmentAdmin(admin.ModelAdmin):
    list_display = ("tracking_number", "user", "status", "recipient_name", "destination", "created_at")
    search_fields = ("tracking_number", "recipient_name", "destination")


@admin.register(StatusUpdate)
class StatusUpdateAdmin(admin.ModelAdmin):
    list_display = ("shipment", "status", "location", "created_at")
    search_fields = ("shipment__tracking_number", "status", "location")
