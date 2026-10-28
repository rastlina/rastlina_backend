"""
orders/shiprocket_client.py
Rastlina — Shiprocket API client.

Handles:
  - Token auth (auto-refresh on 401)
  - Create shipment order
  - Generate AWB (Air Waybill)
  - Request pickup
  - Generate label
  - Track shipment
  - Cancel shipment

Configuration (add to settings.py / .env):
  SHIPROCKET_EMAIL      = "your@email.com"
  SHIPROCKET_PASSWORD   = "yourpassword"
  SHIPROCKET_CHANNEL_ID = 123456   # optional, your sales channel id
  SHIPROCKET_PICKUP_LOCATION = "Primary"  # pickup location name in Shiprocket
"""

import logging
import threading

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

SHIPROCKET_BASE_URL = "https://apiv2.shiprocket.in/v1/external"

# ── Thread-safe token cache ───────────────────────────────────────────────────
_token_lock = threading.Lock()
_cached_token: str | None = None


def _get_fresh_token() -> str:
    """Authenticate and return a fresh JWT token."""
    resp = requests.post(
        f"{SHIPROCKET_BASE_URL}/auth/login",
        json={
            "email": settings.SHIPROCKET_EMAIL,
            "password": settings.SHIPROCKET_PASSWORD,
        },
        timeout=15,
    )
    resp.raise_for_status()
    token = resp.json().get("token")
    if not token:
        raise ValueError("Shiprocket auth response missing token.")
    return token


def get_token() -> str:
    """Return cached token or fetch a new one (thread-safe)."""
    global _cached_token
    with _token_lock:
        if not _cached_token:
            _cached_token = _get_fresh_token()
        return _cached_token


def _invalidate_token():
    global _cached_token
    with _token_lock:
        _cached_token = None


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
    }


def _call(method: str, path: str, **kwargs) -> dict:
    """
    Generic Shiprocket API call with automatic token refresh on 401.
    Raises requests.HTTPError on non-2xx after retry.
    """
    url = f"{SHIPROCKET_BASE_URL}{path}"
    resp = requests.request(method, url, headers=_headers(), timeout=20, **kwargs)

    if resp.status_code == 401:
        logger.info("Shiprocket 401 — refreshing token and retrying.")
        _invalidate_token()
        resp = requests.request(method, url, headers=_headers(), timeout=20, **kwargs)

    resp.raise_for_status()
    return resp.json()


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────────────────────────────

def create_shiprocket_order(order, *, package=None) -> dict:
    """
    Create a Shiprocket order from a Rastlina Order instance.
    Returns the full Shiprocket API response dict.
    """
    if package is None:
        from .shiprocket_sync import parcel_for
        _, package = parcel_for(order)
    import re
    phone = re.sub(r'\D', '', order.phone or '')
    if len(phone) == 12 and phone.startswith('91'):
        phone = phone[2:]
    if len(phone) != 10 or not str(order.zip_code).isdigit() or len(str(order.zip_code)) != 6:
        raise ValueError('A valid 10-digit phone and 6-digit postal code are required.')
    if not all([order.first_name, order.shipping_address, order.city, order.state]):
        raise ValueError('Customer name, address, city and state are required.')
    items = []
    for item in order.items.all():
        items.append({
            "name": item.product_name,
            "sku": item.product.sku if item.product else f"RST-ITEM-{item.pk}",
            "units": item.quantity,
            "selling_price": str(item.price),
            "discount": "",
            "tax": "",
            "hsn": "",
        })

    payload = {
        "order_id": f"RST-{order.id}",
        "order_date": order.created_at.strftime("%Y-%m-%d %H:%M"),
        "pickup_location": getattr(settings, "SHIPROCKET_PICKUP_LOCATION", "Primary"),
        "comment": f"Rastlina order #{order.id}",
        "billing_customer_name": order.first_name,
        "billing_last_name": order.last_name,
        "billing_address": order.shipping_address,
        "billing_address_2": order.apartment or "",
        "billing_city": order.city,
        "billing_pincode": order.zip_code,
        "billing_state": order.state,
        "billing_country": order.country,
        "billing_email": order.email,
        "billing_phone": phone,
        "shipping_is_billing": True,
        "order_items": items,
        "payment_method": "Prepaid",
        "shipping_charges": float(order.shipping_fee),
        "giftwrap_charges": 0,
        "transaction_charges": 0,
        "total_discount": float(order.discount_amount),
        "sub_total": float(order.subtotal),
        "length": package["length"],
        "breadth": package["breadth"],
        "height": package["height"],
        "weight": package["weight"],
    }

    # Attach Shiprocket channel if configured
    channel_id = getattr(settings, "SHIPROCKET_CHANNEL_ID", None)
    if channel_id:
        payload["channel_id"] = channel_id

    return _call("POST", "/orders/create/adhoc", json=payload)


def generate_awb(shipment_id: int, courier_id: int | None = None) -> dict:
    """
    Assign a courier and generate AWB for a shipment.
    If courier_id is None, Shiprocket auto-selects the best courier.
    """
    payload = {"shipment_id": shipment_id}
    if courier_id:
        payload["courier_id"] = courier_id
    return _call("POST", "/courier/assign/awb", json=payload)


def request_pickup(shipment_id: int) -> dict:
    """Schedule a pickup for the given shipment."""
    return _call("POST", "/courier/generate/pickup", json={"shipment_id": [shipment_id]})


def generate_label(shipment_id: int) -> dict:
    """Generate shipping label PDF URL."""
    return _call("POST", "/courier/generate/label", json={"shipment_ids": [shipment_id]})


def track_shipment(order_id: str) -> dict:
    """Track a shipment by Rastlina order ID."""
    return _call("GET", f"/courier/track?order_id={order_id}")


def cancel_shiprocket_order(order_ids: list[int]) -> dict:
    """Cancel Shiprocket orders by Rastlina order ID list."""
    return _call("POST", "/orders/cancel", json={"ids": order_ids})


def get_courier_serviceability(pincode: str, weight: float = 0.5, cod: bool = False) -> dict:
    """Check available couriers for a destination pincode."""
    pickup_pincode = getattr(settings, "SHIPROCKET_PICKUP_PINCODE", "500001")
    params = {
        "pickup_postcode": pickup_pincode,
        "delivery_postcode": pincode,
        "weight": weight,
        "cod": 1 if cod else 0,
    }
    return _call("GET", "/courier/serviceability/", params=params)
