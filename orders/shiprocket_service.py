import logging
from django.utils import timezone
from .models import Order
from .shiprocket_client import (
    cancel_shiprocket_order,
    create_shiprocket_order,
    generate_awb,
    generate_label,
    get_courier_serviceability,
    request_pickup,
    track_shipment,
)

logger = logging.getLogger(__name__)


def create_shipment(order: Order) -> dict:
    """Queue a paid order in Shiprocket New Orders. Courier booking is manual."""
    from .shiprocket_sync import queue_sync
    return queue_sync(order)


def track_order(order: Order) -> dict:
    try:
        data = track_shipment(str(order.id))
        return {"success": True, "tracking": data}
    except Exception as exc:
        logger.warning("track_order failed for Order #%s: %s", order.id, exc)
        return {"success": False, "error": str(exc)}


def cancel_shipment(order: Order) -> dict:
    try:
        resp = cancel_shiprocket_order([order.id])
        return {"success": True, "response": resp}
    except Exception as exc:
        logger.exception("cancel_shipment failed for Order #%s: %s", order.id, exc)
        return {"success": False, "error": str(exc)}


def check_serviceability(pincode: str, weight: float = 0.5) -> dict:
    try:
        data = get_courier_serviceability(pincode, weight=weight, cod=False)
        couriers = data.get("data", {}).get("available_courier_companies", [])
        return {"success": True, "couriers": couriers, "count": len(couriers)}
    except Exception as exc:
        logger.warning("check_serviceability failed for pin %s: %s", pincode, exc)
        return {"success": False, "error": str(exc)}


def get_shipping_label(shipment_id: int) -> dict:
    try:
        resp = generate_label(shipment_id)
        label_url = resp.get("label_url") or resp.get("response", {}).get("label_url")
        return {"success": True, "label_url": label_url}
    except Exception as exc:
        logger.exception("get_shipping_label failed for shipment %s: %s", shipment_id, exc)
        return {"success": False, "error": str(exc)}
