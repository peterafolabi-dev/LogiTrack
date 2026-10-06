import hashlib
import hmac
import json
import time
import uuid
import requests


def sign_payload(secret: str, payload_bytes: bytes) -> str:
    """
    Computes an HMAC-SHA256 hex digest for the given payload using the tenant secret.
    """
    return hmac.new(secret.encode("utf-8"), payload_bytes, hashlib.sha256).hexdigest()


def build_webhook_headers(secret: str, payload_bytes: bytes, event_type: str, delivery_id: str = "") -> dict:
    """
    Generates authenticated enterprise webhook headers including the HMAC-SHA256 signature.
    """
    sig = sign_payload(secret, payload_bytes)
    return {
        "Content-Type": "application/json",
        "User-Agent": "LogiTrack-Webhook/2.0",
        "X-LogiTrack-Signature": f"sha256={sig}",
        "X-LogiTrack-Event": event_type,
        "X-LogiTrack-Delivery": delivery_id or str(uuid.uuid4()),
        "X-LogiTrack-Timestamp": str(int(time.time())),
    }


def deliver_webhook_sync(url: str, secret: str, event_type: str, payload: dict, timeout: int = 10) -> tuple[int, str]:
    """
    Delivers a signed webhook payload synchronously to the recipient URL.
    Returns (status_code, response_body_or_error).
    """
    payload_bytes = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    headers = build_webhook_headers(secret, payload_bytes, event_type)
    
    response = requests.post(
        url,
        data=payload_bytes,
        headers=headers,
        timeout=timeout,
        allow_redirects=False,
    )
    return response.status_code, response.text[:2000]

