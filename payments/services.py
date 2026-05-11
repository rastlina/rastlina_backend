"""
payments/services.py
Rastlina — Payment service layer.

Canonical order lifecycle:
  Pending ──[payment success]──► Processing ──[admin]──► Confirmed ──► Shipped ──► Delivered
               │                      │
               │              [cancel + refund]
               │                      ▼
               └──────────────►  Cancelled

Rules enforced here:
  • Payment success → order_status = "Processing"  (NEVER "Confirmed")
  • "Confirmed" is set by admin only (admin panel or separate confirm endpoint)
  • Auto-refund is triggered when a *paid* order in Processing/Confirmed is cancelled
  • Duplicate refund is prevented via PaymentLog lookup before any Razorpay call
  • All DB mutations run inside select_for_update() atomic transactions
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from orders.models import Order
from .models import PaymentLog
from .razorpay_client import refund_payment, verify_payment_signature

logger = logging.getLogger(__name__)


# ─── Internal helpers ─────────────────────────────────────────────────────────

def _log(
    *,
    event: str,
    source: str,
    order: "Order | None" = None,
    razorpay_order_id: str = "",
    razorpay_payment_id: str = "",
    razorpay_refund_id: str = "",
    amount_paise: int = 0,
    success: bool = True,
    error_code: str = "",
    error_description: str = "",
    raw_payload: "dict | None" = None,
) -> PaymentLog:
    return PaymentLog.objects.create(
        order=order,
        razorpay_order_id=razorpay_order_id or (order.razorpay_order_id if order else ""),
        razorpay_payment_id=razorpay_payment_id,
        razorpay_refund_id=razorpay_refund_id,
        event=event,
        source=source,
        amount_paise=amount_paise,
        success=success,
        error_code=error_code,
        error_description=error_description,
        raw_payload=raw_payload or {},
    )


def _refund_already_initiated(order: Order) -> bool:
    """Returns True if a successful refund log already exists — prevents duplicates."""
    return PaymentLog.objects.filter(
        order=order,
        event="payment.refunded",
        success=True,
    ).exists()


def _capture_already_logged(order: Order) -> bool:
    """Returns True if stock was already deducted — prevents double-deduction on replay."""
    return PaymentLog.objects.filter(
        order=order,
        event="payment.captured",
        success=True,
    ).exists()


def _deduct_stock(order: Order) -> None:
    """
    Deduct variant stock for every item.
    Must be called inside a select_for_update() transaction.
    Raises on inconsistency so the outer transaction rolls back.
    """
    for item in order.items.select_related("variant").select_for_update().all():
        if item.variant:
            variant = item.variant
            if variant.stock >= item.quantity:
                variant.stock -= item.quantity
                variant.save(update_fields=["stock"])
            else:
                raise Exception(
                    f"Stock inconsistency: variant {variant.id} has {variant.stock} "
                    f"units but order line needs {item.quantity}"
                )


def _restore_stock(order: Order) -> None:
    """
    Restore variant stock on cancellation.
    Only meaningful when payment_status == 'Paid' (stock was deducted at capture).
    """
    for item in order.items.select_related("variant").select_for_update().all():
        if item.variant:
            item.variant.stock += item.quantity
            item.variant.save(update_fields=["stock"])


# ─── Capture — client callback ────────────────────────────────────────────────

def capture_payment_from_client(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> dict:
    """
    Called by VerifyPaymentView right after the Razorpay modal closes successfully.

    Critical rule: sets order_status = "Processing" NOT "Confirmed".
    Admin reviews and moves to "Confirmed" when ready to fulfil.
    """
    # Fetch order outside transaction (read-only first look)
    try:
        order = Order.objects.get(razorpay_order_id=razorpay_order_id)
    except Order.DoesNotExist:
        _log(
            event="signature.failed",
            source="client",
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            success=False,
            error_description="Order not found",
        )
        return {"success": False, "error": "Order not found"}

    # Idempotency: exact same payment already stored → safe to return success
    if order.payment_status == "Paid" and order.razorpay_payment_id == razorpay_payment_id:
        return {
            "success": True,
            "message": "Payment already processed",
            "order_id": order.id,
        }

    # Verify Razorpay signature BEFORE any write
    is_valid = verify_payment_signature(
        razorpay_order_id, razorpay_payment_id, razorpay_signature,
    )
    if not is_valid:
        order.payment_status = "Failed"
        order.save(update_fields=["payment_status"])
        _log(
            event="signature.failed",
            source="client",
            order=order,
            razorpay_payment_id=razorpay_payment_id,
            success=False,
            error_description="Signature mismatch",
        )
        return {"success": False, "error": "Payment signature verification failed"}

    # Atomic: lock → update → deduct stock
    with transaction.atomic():
        order = Order.objects.select_for_update().get(id=order.id)

        # Race-condition guard (another process may have already captured)
        if order.payment_status == "Paid":
            return {
                "success": True,
                "message": "Payment already processed",
                "order_id": order.id,
            }

        # ── SET Processing (NOT Confirmed) ────────────────────────────────────
        order.payment_status = "Paid"
        order.order_status = "Processing"
        order.razorpay_payment_id = razorpay_payment_id
        order.save(update_fields=["payment_status", "order_status", "razorpay_payment_id"])

        # Deduct stock only if this is genuinely the first capture event
        if not _capture_already_logged(order):
            _deduct_stock(order)

        _log(
            event="payment.captured",
            source="client",
            order=order,
            razorpay_payment_id=razorpay_payment_id,
            amount_paise=int(order.total_amount * 100),
            success=True,
        )

    logger.info(
        "Payment captured (client): order=%s payment=%s → Processing",
        order.id, razorpay_payment_id,
    )
    return {"success": True, "message": "Payment verified successfully", "order_id": order.id}


# ─── Capture — webhook ───────────────────────────────────────────────────────

def capture_payment_from_webhook(
    rzp_order_id: str,
    rzp_payment_id: str,
    amount_paise: int,
    raw_payload: dict,
) -> None:
    """
    Idempotent. Called from RazorpayWebhookView on payment.captured.
    Applies the same Processing rule as the client path.
    """
    try:
        order = Order.objects.select_for_update().get(razorpay_order_id=rzp_order_id)
    except Order.DoesNotExist:
        _log(
            event="webhook.ignored",
            source="webhook",
            razorpay_order_id=rzp_order_id,
            razorpay_payment_id=rzp_payment_id,
            amount_paise=amount_paise,
            raw_payload=raw_payload,
            error_description="Order not found",
        )
        return

    if order.payment_status == "Paid":
        _log(
            event="webhook.ignored",
            source="webhook",
            order=order,
            razorpay_payment_id=rzp_payment_id,
            amount_paise=amount_paise,
            raw_payload=raw_payload,
            error_description="Already paid — duplicate webhook ignored",
        )
        return

    with transaction.atomic():
        order = Order.objects.select_for_update().get(id=order.id)

        # ── SET Processing (NOT Confirmed) ────────────────────────────────────
        order.payment_status = "Paid"
        order.order_status = "Processing"
        order.razorpay_payment_id = rzp_payment_id
        order.save(update_fields=["payment_status", "order_status", "razorpay_payment_id"])

        if not _capture_already_logged(order):
            _deduct_stock(order)

    _log(
        event="payment.captured",
        source="webhook",
        order=order,
        razorpay_payment_id=rzp_payment_id,
        amount_paise=amount_paise,
        raw_payload=raw_payload,
    )
    logger.info(
        "Payment captured (webhook): order=%s payment=%s → Processing",
        order.id, rzp_payment_id,
    )


# ─── Payment failed — webhook ─────────────────────────────────────────────────

def mark_payment_failed_from_webhook(
    rzp_order_id: str,
    rzp_payment_id: str,
    raw_payload: dict,
) -> None:
    """Called from webhook on payment.failed. Idempotent."""
    try:
        order = Order.objects.get(razorpay_order_id=rzp_order_id)
    except Order.DoesNotExist:
        _log(
            event="webhook.ignored",
            source="webhook",
            razorpay_order_id=rzp_order_id,
            razorpay_payment_id=rzp_payment_id,
            raw_payload=raw_payload,
            error_description="Order not found on failure event",
        )
        return

    # Never overwrite Paid / Refunded status
    if order.payment_status not in ("Pending", "Failed"):
        return

    order.payment_status = "Failed"
    order.save(update_fields=["payment_status"])
    _log(
        event="payment.failed",
        source="webhook",
        order=order,
        razorpay_payment_id=rzp_payment_id,
        success=False,
        raw_payload=raw_payload,
    )
    logger.warning(
        "Payment failed (webhook): order=%s payment=%s", order.id, rzp_payment_id,
    )


# ─── Cancel order + conditional auto-refund ──────────────────────────────────

def cancel_order_with_refund(order: Order) -> dict:
    """
    Cancels an order and handles the refund automatically.

    Case A — paid order in Processing or Confirmed (not yet shipped):
        1. Restore stock
        2. Trigger Razorpay refund API
        3. order_status = "Cancelled", payment_status = "Refunded"

    Case B — order not paid (Pending payment, failed, etc.):
        1. Just cancel, no refund

    Does NOT handle post-delivery cancellations (those go through ReturnRequest).

    Returns: {'success': bool, 'refund_initiated': bool, 'note': str}
    """
    CANCELLABLE_STATUSES = ("Pending", "Processing", "Confirmed")

    if order.order_status == "Cancelled":
        return {"success": False, "error": "This order is already cancelled."}

    if order.order_status not in CANCELLABLE_STATUSES:
        return {
            "success": False,
            "error": (
                f"Cannot cancel — order is '{order.order_status}'. "
                "Only Processing and Confirmed orders can be cancelled. "
                "For delivered orders, please use the exchange/return system."
            ),
        }

    refund_initiated = False
    refund_id = None

    with transaction.atomic():
        order = Order.objects.select_for_update().get(id=order.id)

        # Restore stock only if payment was captured (stock was deducted)
        if order.payment_status == "Paid":
            _restore_stock(order)

        # ── Case A: paid → trigger Razorpay refund ────────────────────────────
        if order.payment_status == "Paid" and order.razorpay_payment_id:

            # Duplicate refund guard
            if _refund_already_initiated(order):
                order.order_status = "Cancelled"
                order.save(update_fields=["order_status"])
                return {
                    "success": True,
                    "refund_initiated": False,
                    "note": "Order cancelled. A refund was already processed earlier.",
                }

            try:
                refund = refund_payment(order.razorpay_payment_id, order.total_amount)
                refund_id = refund.get("id", "")

                order.payment_status = "Refunded"
                order.order_status = "Cancelled"
                order.save(update_fields=["payment_status", "order_status"])
                refund_initiated = True

                _log(
                    event="payment.refunded",
                    source="manual",
                    order=order,
                    razorpay_payment_id=order.razorpay_payment_id,
                    razorpay_refund_id=refund_id,
                    amount_paise=int(order.total_amount * 100),
                    raw_payload=refund,
                )
                logger.info(
                    "Auto-refund on cancel: order=%s refund=%s", order.id, refund_id,
                )
                note = (
                    "Order cancelled. Refund initiated — "
                    "will reflect in 5–7 business days."
                )

            except Exception as exc:
                # Razorpay refund API failed → mark Refund Pending for manual handling
                order.payment_status = "Refund Pending"
                order.order_status = "Cancelled"
                order.save(update_fields=["payment_status", "order_status"])

                _log(
                    event="payment.refunded",
                    source="manual",
                    order=order,
                    razorpay_payment_id=order.razorpay_payment_id,
                    success=False,
                    error_description=str(exc),
                    amount_paise=int(order.total_amount * 100),
                )
                logger.error(
                    "Auto-refund failed for order %s: %s", order.id, exc,
                )
                note = (
                    "Order cancelled. Refund could not be processed automatically — "
                    "our team will process it within 2 business days."
                )

        else:
            # ── Case B: not paid → just cancel ────────────────────────────────
            order.order_status = "Cancelled"
            order.save(update_fields=["order_status"])
            note = "Order cancelled. No payment was collected — no refund required."

    return {
        "success": True,
        "refund_initiated": refund_initiated,
        "refund_id": refund_id,
        "note": note,
    }


# ─── Manual refund (admin use — for approved return requests) ─────────────────

def initiate_refund(order: Order) -> dict:
    """
    Admin-triggered manual refund after approving a ReturnRequest.
    Returns {'success': bool, 'refund_id': str, 'error': str}.
    """
    if order.payment_status != "Paid":
        return {"success": False, "error": "Order is not in 'Paid' state."}
    if not order.razorpay_payment_id:
        return {"success": False, "error": "No Razorpay payment ID on record."}

    if _refund_already_initiated(order):
        return {
            "success": False,
            "error": "A refund has already been processed for this order.",
        }

    try:
        refund = refund_payment(order.razorpay_payment_id, order.total_amount)
        order.payment_status = "Refunded"
        order.save(update_fields=["payment_status"])

        _log(
            event="payment.refunded",
            source="manual",
            order=order,
            razorpay_payment_id=order.razorpay_payment_id,
            razorpay_refund_id=refund.get("id", ""),
            amount_paise=int(order.total_amount * 100),
            raw_payload=refund,
        )
        logger.info(
            "Manual refund initiated: order=%s refund=%s", order.id, refund.get("id"),
        )
        return {"success": True, "refund_id": refund.get("id")}

    except Exception as exc:
        order.payment_status = "Refund Pending"
        order.save(update_fields=["payment_status"])
        _log(
            event="payment.refunded",
            source="manual",
            order=order,
            razorpay_payment_id=order.razorpay_payment_id,
            success=False,
            error_description=str(exc),
            amount_paise=int(order.total_amount * 100),
        )
        logger.error("Manual refund failed for order %s: %s", order.id, exc)
        return {"success": False, "error": str(exc)}