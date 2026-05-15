"""
payments/services.py
Rastlina — Payment capture, cancellation, and refund services.

ARCHITECTURE CHANGE vs previous version:
  _deduct_stock() and _restore_stock() have been REMOVED from this file.
  All stock operations now live exclusively in orders/stock.py and are
  imported via:
    from orders.stock import deduct_stock_for_order, restore_stock_for_order

WHY:
  Having two separate implementations (_deduct_stock here and
  deduct_stock_for_order in orders/services.py) caused:
    - orders/services.py only handled variant stock (not bare product stock)
    - The two functions could silently diverge over time
    - It was impossible to know which function a given call path used

  There is now exactly ONE implementation for each operation.

IDEMPOTENCY STRATEGY:
  stock_deducted  — written in the same atomic block as the deduction.
                    Protects against double-deduction if the webhook fires
                    after the client callback already captured payment.
  stock_restored  — written in the same atomic block as the restoration.
                    Protects against double-restoration on concurrent
                    cancel calls or if approve + cancel race each other.
  coupon_applied  — same pattern; incremented once at capture, not checkout.
  exchange_consumed — same pattern.

NOTE ON WEBHOOKS:
  The webhook endpoint exists in the codebase but is not actively used in
  production (no RAZORPAY_WEBHOOK_SECRET configured). All payment capture
  flows go through capture_payment_from_client(). The webhook handler is
  kept for future use and is fully idempotent.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from orders.models import ExchangeCode, Order
from orders.stock import deduct_stock_for_order, restore_stock_for_order   # ← single source
from .models import PaymentLog
from .razorpay_client import refund_payment, verify_payment_signature

logger = logging.getLogger(__name__)


# ─── Logging helper ───────────────────────────────────────────────────────────

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
) -> None:
    """
    Create an immutable PaymentLog entry.
    Deliberately does NOT raise — logging failure must never abort a payment.
    """
    try:
        PaymentLog.objects.create(
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
    except Exception as exc:
        logger.error("PaymentLog write failed (non-fatal): %s", exc)


def _refund_already_initiated(order: Order) -> bool:
    """Secondary guard — checks PaymentLog for a successful refund entry."""
    return PaymentLog.objects.filter(
        order=order,
        event="payment.refunded",
        success=True,
    ).exists()


# ─── Coupon + exchange consumption ───────────────────────────────────────────

def _consume_coupon_and_exchange(order: Order) -> None:
    """
    Called once at payment capture (not at checkout).
    Increments coupon uses_count and marks exchange code as used.

    Uses the idempotency flags on Order to prevent double-consumption.
    Call this INSIDE the payment capture transaction after acquiring the order lock.
    """
    from store.models import Coupon  # local import to avoid circular

    # Coupon
    if order.coupon_code and not order.coupon_applied:
        try:
            coupon = Coupon.objects.select_for_update().get(
                code=order.coupon_code, active=True,
            )
            coupon.uses_count += 1
            coupon.save(update_fields=["uses_count"])
            order.coupon_applied = True
        except Coupon.DoesNotExist:
            logger.warning(
                "Coupon %s not found during capture for order %s",
                order.coupon_code, order.id,
            )

    # Exchange code
    if order.exchange_code_used and not order.exchange_consumed:
        try:
            ex_code = ExchangeCode.objects.select_for_update().get(
                code=order.exchange_code_used,
            )
            if not ex_code.is_used:
                ex_code.is_used = True
                ex_code.used_at = timezone.now()
                ex_code.save(update_fields=["is_used", "used_at"])
            order.exchange_consumed = True
        except ExchangeCode.DoesNotExist:
            logger.warning(
                "Exchange code %s not found during capture for order %s",
                order.exchange_code_used, order.id,
            )


# ─── Payment capture — client callback ────────────────────────────────────────

def capture_payment_from_client(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> dict:
    """
    Called by VerifyPaymentView right after the Razorpay modal closes.

    Lifecycle:
      1. Find order by razorpay_order_id.
      2. Verify Razorpay signature (before any write).
      3. Inside atomic+lock: if already Paid → return early (idempotent).
      4. Set order to Processing, deduct stock (once), burn coupon/exchange (once).
      5. Log.

    Stock deduction uses deduct_stock_for_order from orders/stock.py.
    """
    # ── Step 1: find order ────────────────────────────────────────────────────
    try:
        order = Order.objects.get(razorpay_order_id=razorpay_order_id)
    except Order.DoesNotExist:
        _log(
            event="signature.failed", source="client",
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            success=False, error_description="Order not found",
        )
        return {"success": False, "error": "Order not found"}

    # ── Step 2: verify signature BEFORE any write ─────────────────────────────
    is_valid = verify_payment_signature(
        razorpay_order_id, razorpay_payment_id, razorpay_signature,
    )
    if not is_valid:
        if order.payment_status == "Pending":
            order.payment_status = "Failed"
            order.save(update_fields=["payment_status"])
        _log(
            event="signature.failed", source="client",
            order=order, razorpay_payment_id=razorpay_payment_id,
            success=False, error_description="Signature mismatch",
        )
        return {"success": False, "error": "Payment signature verification failed"}

    # ── Step 3 + 4: atomic lock → write ──────────────────────────────────────
    with transaction.atomic():
        order = Order.objects.select_for_update().get(id=order.id)

        # Idempotency: exact same payment already recorded
        if order.payment_status == "Paid" and order.razorpay_payment_id == razorpay_payment_id:
            return {
                "success": True,
                "message": "Payment already processed",
                "order_id": order.id,
            }

        # Reject a different payment_id for an already-paid order
        if order.payment_status == "Paid":
            return {
                "success": False,
                "error": "Order already paid with a different payment.",
            }

        order.payment_status = "Paid"
        order.order_status = "Processing"
        order.razorpay_payment_id = razorpay_payment_id

        # ── Stock deduction (idempotent via stock_deducted flag) ──────────────
        if not order.stock_deducted:
            deduct_stock_for_order(order)   # raises on inconsistency → rolls back
            order.stock_deducted = True

        # ── Coupon + exchange consumption ─────────────────────────────────────
        _consume_coupon_and_exchange(order)

        order.save(update_fields=[
            "payment_status", "order_status", "razorpay_payment_id",
            "stock_deducted", "coupon_applied", "exchange_consumed",
        ])

    # ── Step 5: log AFTER transaction (non-blocking, best-effort) ────────────
    _log(
        event="payment.captured", source="client",
        order=order, razorpay_payment_id=razorpay_payment_id,
        amount_paise=int(order.total_amount * 100),
    )

    logger.info(
        "Payment captured (client): order=%s payment=%s → Processing",
        order.id, razorpay_payment_id,
    )
    return {"success": True, "message": "Payment verified successfully", "order_id": order.id}


# ─── Payment capture — Razorpay webhook ──────────────────────────────────────

def capture_payment_from_webhook(
    rzp_order_id: str,
    rzp_payment_id: str,
    amount_paise: int,
    raw_payload: dict,
) -> None:
    """
    Idempotent. Called from RazorpayWebhookView on payment.captured event.

    The entire flow is inside a SINGLE transaction.atomic() with
    select_for_update() so the idempotency check and the write are atomic.

    Stock deduction uses deduct_stock_for_order from orders/stock.py.
    """
    with transaction.atomic():
        try:
            order = Order.objects.select_for_update().get(razorpay_order_id=rzp_order_id)
        except Order.DoesNotExist:
            _log(
                event="webhook.ignored", source="webhook",
                razorpay_order_id=rzp_order_id,
                razorpay_payment_id=rzp_payment_id,
                amount_paise=amount_paise,
                raw_payload=raw_payload,
                error_description="Order not found",
            )
            return

        # Idempotency: payment already captured
        if order.payment_status == "Paid":
            _log(
                event="webhook.ignored", source="webhook",
                order=order,
                razorpay_order_id=rzp_order_id,
                razorpay_payment_id=rzp_payment_id,
                amount_paise=amount_paise,
                raw_payload=raw_payload,
                error_description="Already paid — duplicate webhook ignored",
            )
            return

        order.payment_status = "Paid"
        order.order_status = "Processing"
        order.razorpay_payment_id = rzp_payment_id

        if not order.stock_deducted:
            deduct_stock_for_order(order)
            order.stock_deducted = True

        _consume_coupon_and_exchange(order)

        order.save(update_fields=[
            "payment_status", "order_status", "razorpay_payment_id",
            "stock_deducted", "coupon_applied", "exchange_consumed",
        ])

        _log(
            event="payment.captured", source="webhook",
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
    """
    Called on payment.failed webhook. Idempotent.
    Never overwrites Paid/Refunded status.
    """
    try:
        order = Order.objects.get(razorpay_order_id=rzp_order_id)
    except Order.DoesNotExist:
        _log(
            event="webhook.ignored", source="webhook",
            razorpay_order_id=rzp_order_id,
            razorpay_payment_id=rzp_payment_id,
            raw_payload=raw_payload,
            error_description="Order not found on failure event",
        )
        return

    # NEVER overwrite Paid / Refunded / Refund Pending
    if order.payment_status not in ("Pending", "Failed"):
        _log(
            event="webhook.ignored", source="webhook",
            order=order, razorpay_payment_id=rzp_payment_id,
            raw_payload=raw_payload,
            error_description=f"Ignoring failed event — order already {order.payment_status}",
        )
        return

    order.payment_status = "Failed"
    order.save(update_fields=["payment_status"])

    _log(
        event="payment.failed", source="webhook",
        order=order, razorpay_payment_id=rzp_payment_id,
        success=False, raw_payload=raw_payload,
    )
    logger.warning("Payment failed (webhook): order=%s payment=%s", order.id, rzp_payment_id)


# ─── Order cancellation + conditional auto-refund ─────────────────────────────

def cancel_order_with_refund(order: Order) -> dict:
    """
    Cancels an order and handles refund + stock restoration atomically.

    Cancellable statuses: Pending, Processing, Confirmed
    Not cancellable: Shipped, Delivered, Cancelled

    Stock restore:
      - Delegates to restore_stock_for_order (orders/stock.py).
      - Guarded by order.stock_deducted AND order.stock_restored flags.

    Refund:
      - Triggered automatically if order was paid.
      - Guarded by PaymentLog check + payment_status check inside lock.
    """
    CANCELLABLE = ("Pending", "Processing", "Confirmed")

    if order.order_status == "Cancelled":
        return {"success": False, "error": "This order is already cancelled."}

    if order.order_status not in CANCELLABLE:
        return {
            "success": False,
            "error": (
                f"Cannot cancel — order is '{order.order_status}'. "
                "Only orders not yet shipped can be cancelled. "
                "For delivered orders, use the exchange/return system."
            ),
        }

    refund_initiated = False
    refund_id = None
    note = ""

    with transaction.atomic():
        order = Order.objects.select_for_update().get(id=order.id)

        # Double-check inside lock (concurrent cancel may have beaten us)
        if order.order_status == "Cancelled":
            return {"success": False, "error": "Order was already cancelled."}

        if order.order_status not in CANCELLABLE:
            return {"success": False, "error": f"Order status changed to {order.order_status}."}

        # ── Restore stock (idempotent via stock_restored flag) ────────────────
        if order.stock_deducted and not order.stock_restored:
            restore_stock_for_order(order)
            order.stock_restored = True

        # ── Case A: Paid → trigger Razorpay refund ────────────────────────────
        if order.payment_status == "Paid" and order.razorpay_payment_id:

            if _refund_already_initiated(order):
                order.order_status = "Cancelled"
                order.save(update_fields=["order_status", "stock_restored"])
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
                order.save(update_fields=[
                    "payment_status", "order_status", "stock_restored",
                ])
                refund_initiated = True
                note = "Order cancelled. Refund initiated — will reflect in 5–7 business days."

                _log(
                    event="payment.refunded", source="manual",
                    order=order,
                    razorpay_payment_id=order.razorpay_payment_id,
                    razorpay_refund_id=refund_id,
                    amount_paise=int(order.total_amount * 100),
                    raw_payload=refund,
                )

            except Exception as exc:
                order.payment_status = "Refund Pending"
                order.order_status = "Cancelled"
                order.save(update_fields=[
                    "payment_status", "order_status", "stock_restored",
                ])
                _log(
                    event="payment.refunded", source="manual",
                    order=order,
                    razorpay_payment_id=order.razorpay_payment_id,
                    success=False, error_description=str(exc),
                    amount_paise=int(order.total_amount * 100),
                )
                logger.error("Auto-refund failed for order %s: %s", order.id, exc)
                note = (
                    "Order cancelled. Refund could not be processed automatically — "
                    "our team will handle it within 2 business days."
                )

        # ── Case B: not paid → just cancel ────────────────────────────────────
        else:
            order.order_status = "Cancelled"
            order.save(update_fields=["order_status", "stock_restored"])
            note = "Order cancelled. No payment was collected — no refund required."

    logger.info("Order %s cancelled. Refund initiated: %s", order.id, refund_initiated)
    return {
        "success": True,
        "refund_initiated": refund_initiated,
        "refund_id": refund_id,
        "note": note,
    }


# ─── Manual refund — admin-triggered (for approved return requests) ───────────

def initiate_refund(order: Order, *, restore_stock: bool = False) -> dict:
    """
    Admin-triggered refund after approving an OrderReturnRequest.

    IMPORTANT: restore_stock should always be False when called from
    process_refund_for_return(), because stock was already restored in
    approve_return_request(). Passing True here would double-restore.

    The restore_stock parameter is retained for edge-case backward
    compatibility only (e.g. a direct admin call that skipped approval).
    Normal flow: approve_return_request() → process_refund_for_return()
    with restore_stock=False.

    Idempotency:
      - Checks PaymentLog for existing refund log.
      - Checks payment_status inside row lock.

    Returns: {'success': bool, 'refund_id': str, 'error': str}
    """
    with transaction.atomic():
        order = Order.objects.select_for_update().get(id=order.id)

        if order.payment_status != "Paid":
            return {
                "success": False,
                "error": f"Order payment_status is '{order.payment_status}', not Paid.",
            }

        if not order.razorpay_payment_id:
            return {"success": False, "error": "No Razorpay payment ID on record."}

        if _refund_already_initiated(order):
            return {
                "success": False,
                "error": "A refund has already been processed for this order.",
            }

        # Optionally restore stock — only if caller explicitly requests it
        # AND the guards confirm it hasn't been done yet.
        if restore_stock and order.stock_deducted and not order.stock_restored:
            restore_stock_for_order(order)
            order.stock_restored = True

        try:
            refund = refund_payment(order.razorpay_payment_id, order.total_amount)
            refund_id = refund.get("id", "")
            order.payment_status = "Refunded"
            order.save(update_fields=["payment_status", "stock_restored"])

            _log(
                event="payment.refunded", source="manual",
                order=order,
                razorpay_payment_id=order.razorpay_payment_id,
                razorpay_refund_id=refund_id,
                amount_paise=int(order.total_amount * 100),
                raw_payload=refund,
            )
            logger.info("Manual refund initiated: order=%s refund=%s", order.id, refund_id)
            return {"success": True, "refund_id": refund_id}

        except Exception as exc:
            order.payment_status = "Refund Pending"
            order.save(update_fields=["payment_status", "stock_restored"])
            _log(
                event="payment.refunded", source="manual",
                order=order,
                razorpay_payment_id=order.razorpay_payment_id,
                success=False, error_description=str(exc),
                amount_paise=int(order.total_amount * 100),
            )
            logger.error("Manual refund failed for order %s: %s", order.id, exc)
            return {"success": False, "error": str(exc)}