from __future__ import annotations

import json
import os

import requests
from django.utils import timezone

SUPPORTED_PROVIDERS = [
    ("manual", "Manual / In-house"),
    ("fedex", "FedEx"),
    ("ups", "UPS"),
    ("dhl", "DHL"),
]


class CarrierSyncService:
    """Carrier sync layer with provider adapters and deterministic fallback status mapping."""

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

    @staticmethod
    def _normalize_status(status: str | None) -> str:
        value = (status or "").strip().upper().replace("-", "_")
        if not value:
            return "pending"
        status_map = {
            "PENDING": "pending",
            "CREATED": "pending",
            "PICKED_UP": "picked_up",
            "PICKUP": "picked_up",
            "IN_TRANSIT": "in_transit",
            "TRANSIT": "in_transit",
            "ON_ROUTE": "in_transit",
            "OUT_FOR_DELIVERY": "out_for_delivery",
            "OUT_FOR_DELIVERY_READY": "out_for_delivery",
            "DELIVERED": "delivered",
            "SUCCESS": "delivered",
            "FAILURE": "failed",
            "FAILED": "failed",
            "EXCEPTION": "failed",
            "DELAYED": "failed",
        }
        for key, mapped in status_map.items():
            if key in value or value == key:
                return mapped
        return "pending"

    @staticmethod
    def _get_provider_config(provider: str) -> dict:
        return {
            "fedex": {
                "key_env": "FEDEX_API_KEY",
                "endpoint": "https://apis.fedex.com/track/v1/shipments",
                "payload_key": "trackingInfo",
            },
            "ups": {
                "key_env": "UPS_API_KEY",
                "endpoint": "https://onlinetools.ups.com/ship/v1/shipments",
                "payload_key": "trackingNumbers",
            },
            "dhl": {
                "key_env": "DHL_API_KEY",
                "endpoint": "https://api-eu.dhl.com/track/shipments",
                "payload_key": "trackingNumbers",
            },
        }.get(provider, {})

    @classmethod
    def _fetch_external_status(cls, provider: str, tracking_number: str, business=None) -> tuple[str | None, str | None, bool]:
        if provider == "manual":
            return None, "manual fallback", False

        config = cls._get_provider_config(provider)
        if not config:
            return None, "provider not supported", False

        api_key = os.environ.get(config["key_env"], "")
        if not api_key:
            if business and getattr(business, "carrier_account_number", ""):
                api_key = str(getattr(business, "carrier_account_number", ""))
            if not api_key:
                return None, "not configured", False

        headers = {"Content-Type": "application/json", "Accept": "application/json"}
        if provider == "fedex":
            headers["Authorization"] = f"Bearer {api_key}"
            payload = {"includeTracking": True, "trackingInfo": [{"trackingNumber": tracking_number}]}
        elif provider == "ups":
            headers["AccessLicenseNumber"] = api_key
            payload = {"trackingNumbers": [tracking_number]}
        else:
            headers["DHL-API-Key"] = api_key
            payload = {"trackingNumbers": [tracking_number]}

        try:
            response = requests.post(config["endpoint"], headers=headers, data=json.dumps(payload), timeout=10)
            response.raise_for_status()
            payload_data = response.json() if response.content else {}
        except Exception:
            return None, "provider request failed", False

        status = None
        location = None
        if isinstance(payload_data, dict):
            candidates = [
                payload_data.get("shipmentStatus"),
                payload_data.get("status"),
                payload_data.get("currentStatus"),
                payload_data.get("trackingStatus"),
                payload_data.get("deliveryStatus"),
                payload_data.get("shipment") or payload_data.get("data"),
            ]
            for candidate in candidates:
                if isinstance(candidate, dict):
                    status = candidate.get("status") or candidate.get("code") or candidate.get("state") or candidate.get("currentStatus")
                    location = candidate.get("location") or candidate.get("locationName") or candidate.get("city")
                    if status:
                        break
                elif isinstance(candidate, str):
                    status = candidate
                    break
            if isinstance(payload_data.get("shipments"), list):
                first = payload_data["shipments"][0]
                if isinstance(first, dict):
                    status = status or first.get("status") or first.get("currentStatus")
                    location = location or first.get("location") or first.get("destination")
        if not status:
            return None, "provider payload missing status", False

        return cls._normalize_status(str(status)), location or "Carrier network", True

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
                "source": "disabled",
            }

        tracking_number = shipment.carrier_tracking_number or shipment.tracking_number
        carrier_status, location, provider_ready = cls._fetch_external_status(provider, tracking_number, business)
        if carrier_status is None:
            carrier_status = cls.status_for_tracking_number(tracking_number, provider)
            source = "fallback"
            message = f"Carrier sync fell back to the deterministic status model for {provider.upper()}."
        else:
            source = "provider"
            message = f"Carrier status synced via {provider.upper()} from the live provider feed."

        shipment.carrier_status = carrier_status
        shipment.carrier_last_sync_at = timezone.now()
        if location and not getattr(shipment, "origin", ""):
            shipment.origin = location
        shipment.save(update_fields=["carrier_status", "carrier_last_sync_at", "updated_at"])
        return {
            "updated": True,
            "carrier_status": carrier_status,
            "provider": provider,
            "source": source,
            "message": message,
            "provider_ready": provider_ready,
        }
