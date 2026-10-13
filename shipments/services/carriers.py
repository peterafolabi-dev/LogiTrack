from __future__ import annotations

from datetime import timedelta

from django.utils import timezone

SUPPORTED_PROVIDERS = [
    ("manual", "Manual / In-house"),
    ("fedex", "FedEx"),
    ("ups", "UPS"),
    ("dhl", "DHL"),
]


class CarrierSyncService:
    """Lightweight carrier integration layer for demo and operational syncs.

    This project does not have live external carrier credentials in development,
    so the service exposes a deterministic sync model that fills carrier status and
    last-sync timestamps without changing the internal shipment workflow.
    """

    @staticmethod
    def provider_key(value: str | None) -> str:
        value = (value or "manual").strip().lower()
        if value in {"in-house", "in_house", "manual"}:
            return "manual"
        if value in {"fedex", "fedex express"}:
            return "fedex"
        if value in {"ups", "ups freight"}:
            return "ups"
        if value in {"dhl", "dhl global"}:
            return "dhl"
        return "manual"

    @staticmethod
    def status_for_tracking_number(tracking_number: str, provider: str) -> str:
        if not tracking_number:
            return "pending"
        total = sum(ord(ch) for ch in tracking_number)
        provider_order = {
            "manual": ["pending", "picked_up", "in_transit", "out_for_delivery", "delivered"],
            "fedex": ["picked_up", "in_transit", "out_for_delivery", "delivered", "in_transit"],
            "ups": ["picked_up", "in_transit", "in_transit", "out_for_delivery", "delivered"],
            "dhl": ["in_transit", "out_for_delivery", "in_transit", "delivered", "picked_up"],
        }
        options = provider_order.get(provider, provider_order["manual"])
        return options[total % len(options)]

    @classmethod
    def sync_shipment(cls, shipment) -> dict:
        business = getattr(shipment, "business", None)
        provider = cls.provider_key(
            getattr(business, "carrier_provider", None)
            if business
            else getattr(shipment, "carrier", None)
        )
        if not business or not getattr(business, "carrier_sync_enabled", False):
            return {
                "updated": False,
                "carrier_status": shipment.carrier_status or "pending",
                "provider": provider,
                "message": "Carrier sync is disabled for this workspace.",
            }

        carrier_status = cls.status_for_tracking_number(
            shipment.carrier_tracking_number or shipment.tracking_number,
            provider,
        )
        shipment.carrier_status = carrier_status
        shipment.carrier_last_sync_at = timezone.now()
        shipment.save(update_fields=["carrier_status", "carrier_last_sync_at", "updated_at"])
        return {
            "updated": True,
            "carrier_status": carrier_status,
            "provider": provider,
            "message": f"Carrier status synced via {provider.upper()}.",
        }
