"""
payments/services.py
Rastlina — Payment service layer.
All business logic for capturing, failing, and refunding payments lives here.
Views are thin; they call these functions and return the result.
"""

import logging
from decimal import Decimal

from django.db import transaction
from django.utils import timezone

from orders.models import Order
from .models import PaymentLog
from .razorpay_client import refund_payment, verify_payment_signature

logger = logging.getLogger(__name__)


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _log(
    *,
    event: str,
    source: str,
    order: Order | None = None,
    razorpay_order_id: str = '',
    razorpay_payment_id: str = '',
    razorpay_refund_id: str = '',
    amount_paise: int = 0,
    success: bool = True,
    error_code: str = '',
    error_description: str = '',
    raw_payload: dict | None = None,
) -> PaymentLog:
    return PaymentLog.objects.create(
        order=order,
        razorpay_order_id=razorpay_order_id or (order.razorpay_order_id if order else ''),
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


def _deduct_stock(order: Order) -> None:
    """Deduct variant stock for every item in this order (called once on payment capture)."""
    for item in order.items.select_related('variant').all():
        if item.variant:
            variant = item.variant
            # Guard against going negative
            deduct = min(item.quantity, variant.stock)
            if deduct > 0:
                variant.stock = max(0, variant.stock - deduct)
                variant.save(update_fields=['stock'])


# ─── Capture (client callback path) ──────────────────────────────────────────

def capture_payment_from_client(
    razorpay_order_id: str,
    razorpay_payment_id: str,
    razorpay_signature: str,
) -> dict:
    """
    Called from VerifyPaymentView (client callback after Razorpay modal closes).
    1. Verify signature
    2. Mark order Paid / Confirmed
    3. Deduct stock
    4. Log event
    Returns a dict with 'success', 'message' / 'error'.
    """
    # Resolve order
    try:
        order = Order.objects.select_for_update().get(razorpay_order_id=razorpay_order_id)
    except Order.DoesNotExist:
        _log(
            event='signature.failed',
            source='client',
            razorpay_order_id=razorpay_order_id,
            razorpay_payment_id=razorpay_payment_id,
            success=False,
            error_description='Order not found',
        )
        return {'success': False, 'error': 'Order not found'}

    # Idempotency — already processed
    if order.payment_status == 'Paid':
        return {'success': True, 'message': 'Already processed', 'order_id': order.id}

    # Verify signature
    is_valid = verify_payment_signature(
        razorpay_order_id, razorpay_payment_id, razorpay_signature,
    )

    if not is_valid:
        with transaction.atomic():
            order.payment_status = 'Failed'
            order.save(update_fields=['payment_status'])
        _log(
            event='signature.failed',
            source='client',
            order=order,
            razorpay_payment_id=razorpay_payment_id,
            success=False,
            error_description='Signature mismatch',
        )
        return {'success': False, 'error': 'Payment signature verification failed'}

    # Mark paid
    with transaction.atomic():
        order.payment_status = 'Paid'
        order.order_status = 'Confirmed'
        order.razorpay_payment_id = razorpay_payment_id
        order.save(update_fields=['payment_status', 'order_status', 'razorpay_payment_id'])
        _deduct_stock(order)

    _log(
        event='payment.captured',
        source='client',
        order=order,
        razorpay_payment_id=razorpay_payment_id,
        amount_paise=int(order.total_amount * 100),
        success=True,
    )
    logger.info("Payment captured (client): order=%s payment=%s", order.id, razorpay_payment_id)
    return {'success': True, 'message': 'Payment verified successfully', 'order_id': order.id}


# ─── Capture (webhook path) ───────────────────────────────────────────────────

def capture_payment_from_webhook(
    rzp_order_id: str,
    rzp_payment_id: str,
    amount_paise: int,
    raw_payload: dict,
) -> None:
    """
    Called from the Razorpay webhook handler on payment.captured event.
    Idempotent — safe to call multiple times for the same payment.
    """
    try:
        order = Order.objects.select_for_update().get(razorpay_order_id=rzp_order_id)
    except Order.DoesNotExist:
        _log(
            event='webhook.ignored',
            source='webhook',
            razorpay_order_id=rzp_order_id,
            razorpay_payment_id=rzp_payment_id,
            amount_paise=amount_paise,
            raw_payload=raw_payload,
            error_description='Order not found',
        )
        return

    if order.payment_status == 'Paid':
        _log(
            event='webhook.ignored',
            source='webhook',
            order=order,
            razorpay_payment_id=rzp_payment_id,
            amount_paise=amount_paise,
            raw_payload=raw_payload,
            error_description='Already paid — duplicate webhook',
        )
        return

    with transaction.atomic():
        order.payment_status = 'Paid'
        order.order_status = 'Confirmed'
        order.razorpay_payment_id = rzp_payment_id
        order.save(update_fields=['payment_status', 'order_status', 'razorpay_payment_id'])
        _deduct_stock(order)

    _log(
        event='payment.captured',
        source='webhook',
        order=order,
        razorpay_payment_id=rzp_payment_id,
        amount_paise=amount_paise,
        raw_payload=raw_payload,
    )
    logger.info("Payment captured (webhook): order=%s payment=%s", order.id, rzp_payment_id)


def mark_payment_failed_from_webhook(
    rzp_order_id: str,
    rzp_payment_id: str,
    raw_payload: dict,
) -> None:
    """Called from webhook on payment.failed."""
    try:
        order = Order.objects.get(razorpay_order_id=rzp_order_id)
    except Order.DoesNotExist:
        _log(
            event='webhook.ignored',
            source='webhook',
            razorpay_order_id=rzp_order_id,
            razorpay_payment_id=rzp_payment_id,
            raw_payload=raw_payload,
            error_description='Order not found on failure event',
        )
        return

    if order.payment_status not in ('Pending', 'Failed'):
        return  # Don't overwrite Paid / Refunded

    order.payment_status = 'Failed'
    order.save(update_fields=['payment_status'])
    _log(
        event='payment.failed',
        source='webhook',
        order=order,
        razorpay_payment_id=rzp_payment_id,
        success=False,
        raw_payload=raw_payload,
    )
    logger.warning("Payment failed (webhook): order=%s payment=%s", order.id, rzp_payment_id)


# ─── Refund ───────────────────────────────────────────────────────────────────

def initiate_refund(order: Order) -> dict:
    """
    Trigger a Razorpay refund for a paid order.
    Returns {'success': True/False, 'refund_id': ..., 'error': ...}.
    """
    if order.payment_status != 'Paid':
        return {'success': False, 'error': 'Order is not in Paid state'}
    if not order.razorpay_payment_id:
        return {'success': False, 'error': 'No Razorpay payment ID on record'}

    try:
        refund = refund_payment(order.razorpay_payment_id, order.total_amount)
        order.payment_status = 'Refunded'
        order.save(update_fields=['payment_status'])

        _log(
            event='payment.refunded',
            source='manual',
            order=order,
            razorpay_payment_id=order.razorpay_payment_id,
            razorpay_refund_id=refund.get('id', ''),
            amount_paise=int(order.total_amount * 100),
            raw_payload=refund,
        )
        return {'success': True, 'refund_id': refund.get('id')}

    except Exception as exc:
        order.payment_status = 'Refund Pending'
        order.save(update_fields=['payment_status'])
        _log(
            event='payment.refunded',
            source='manual',
            order=order,
            razorpay_payment_id=order.razorpay_payment_id,
            success=False,
            error_description=str(exc),
            amount_paise=int(order.total_amount * 100),
        )
        logger.error("Refund failed for order %s: %s", order.id, exc)
        return {'success': False, 'error': str(exc)}