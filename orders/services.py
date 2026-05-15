"""
orders/services.py
Rastlina — Order-level business logic services.

All stock operations are delegated to orders/stock.py.
Payment/refund logic lives in payments/services.py.

Public API:
  cancel_order(order)
  approve_exchange_request(return_request_id)
  approve_return_request(return_request_id)
  process_refund_for_return(return_request_id)

STOCK RESTORE POLICY (business rules):
  - Exchange approval → restore stock (customer sends defective item back;
    that stock slot is freed so a fresh unit can be shipped).
  - Return approval   → restore stock (physical item comes back to warehouse).
  - Refund processing → NO stock change (stock was already restored at approval).
  - Cancellation      → restore stock (handled in payments/services.py).

IDEMPOTENCY:
  Stock is restored at most once per order, guarded by:
    order.stock_deducted  — was stock ever taken?  (must be True to restore)
    order.stock_restored  — was stock already put back?  (must be False to restore)
  For return requests, an additional per-request guard exists:
    OrderReturnRequest.stock_restored — prevents double-restore if the admin
    action is accidentally run twice on the same request before the order flag
    propagates (extremely unlikely but defended against).
"""

import logging

from django.db import transaction
from django.utils import timezone

from .stock import restore_stock_for_order          # ← single source of truth

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _do_restore_stock(order, req=None) -> bool:
    """
    Internal helper: attempt to restore stock for an order inside an
    already-open atomic block with the order row locked.

    Guards:
      1. order.stock_deducted must be True  (stock was actually taken)
      2. order.stock_restored must be False (not already put back)
      3. If req is given, req.stock_restored must be False (per-request guard)

    Returns True if stock was restored, False if skipped.
    """
    if not order.stock_deducted:
        logger.info(
            "Stock restore skipped for order #%s — stock was never deducted.",
            order.id,
        )
        return False

    if order.stock_restored:
        logger.warning(
            "Stock restore skipped for order #%s — already restored (order flag).",
            order.id,
        )
        return False

    if req is not None and req.stock_restored:
        logger.warning(
            "Stock restore skipped for order #%s — already restored (request flag on %s #%s).",
            order.id, type(req).__name__, req.id,
        )
        return False

    restore_stock_for_order(order)          # raises on hard errors → rolls back
    order.stock_restored = True
    order.save(update_fields=["stock_restored"])

    if req is not None:
        req.stock_restored = True
        # Caller must include stock_restored in update_fields when saving req

    logger.info(
        "Stock restored for order #%s (triggered by %s).",
        order.id,
        f"{type(req).__name__} #{req.id}" if req else "cancellation",
    )
    return True


# ─────────────────────────────────────────────────────────────────────────────
# ORDER CANCELLATION
# ─────────────────────────────────────────────────────────────────────────────

def cancel_order(order) -> dict:
    """
    Thin wrapper — delegates to payments.services.cancel_order_with_refund
    which handles stock restore + refund + status update atomically.
    Imported here so views only need to import from orders.services.
    """
    from payments.services import cancel_order_with_refund
    return cancel_order_with_refund(order)


# ─────────────────────────────────────────────────────────────────────────────
# EXCHANGE REQUEST APPROVAL  (defective item → exchange code + stock restore)
# ─────────────────────────────────────────────────────────────────────────────

def approve_exchange_request(return_request_id: int) -> dict:
    """
    Admin approves a ReturnRequest (exchange request for a defective item).

    Flow:
      1. Lock the ReturnRequest row.
      2. Restore stock (customer sends defective item back → that unit
         re-enters inventory as a fresh slot).
         Guard: only if stock_deducted=True AND stock_restored=False.
      3. Set status = 'Approved'.
      4. Save triggers the post_save signal → ExchangeCode auto-created.
      5. No monetary refund — customer gets an exchange code instead.

    WHY stock is restored here:
      The original item is returned (defective). We ship a new unit.
      If we didn't restore, the warehouse count would be permanently off
      by the quantity of every approved exchange.

    Returns: {'success': bool, 'exchange_code': str | None, 'error': str}
    """
    from .models import ReturnRequest

    try:
        with transaction.atomic():
            req = ReturnRequest.objects.select_for_update().get(pk=return_request_id)

            if req.status != 'Pending':
                return {
                    'success': False,
                    'error': f"Request is already '{req.status}' — cannot approve again.",
                }

            # ── Re-lock the Order row for stock operations ────────────────────
            from .models import Order
            order = Order.objects.select_for_update().get(pk=req.order_id)

            # ── Restore stock ─────────────────────────────────────────────────
            _do_restore_stock(order, req=None)
            # Note: ReturnRequest (exchange) doesn't have its own stock_restored
            # field — the order-level flag is sufficient here. The per-request
            # guard (req.stock_restored) applies only to OrderReturnRequest.

            # ── Approve ───────────────────────────────────────────────────────
            req.status = 'Approved'
            req.approved_at = timezone.now()
            req.save()          # post_save signal → creates ExchangeCode

        # Re-fetch to get the exchange_code populated by the signal
        req.refresh_from_db()
        code = req.exchange_code.code if req.exchange_code else None

        logger.info(
            "Exchange request #%s approved. Exchange code: %s",
            return_request_id, code,
        )
        return {'success': True, 'exchange_code': code}

    except ReturnRequest.DoesNotExist:
        return {'success': False, 'error': 'Exchange request not found.'}
    except Exception as exc:
        logger.error("approve_exchange_request failed: %s", exc)
        return {'success': False, 'error': str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# PHYSICAL RETURN APPROVAL  (admin approves → stock restore; refund is separate)
# ─────────────────────────────────────────────────────────────────────────────

def approve_return_request(return_request_id: int) -> dict:
    """
    Admin approves a physical OrderReturnRequest.

    Flow:
      1. Lock the OrderReturnRequest row.
      2. Lock the Order row.
      3. Restore stock (item is physically coming back to warehouse).
         Guard: only if stock_deducted=True AND stock_restored=False
                     AND req.stock_restored=False (per-request guard).
      4. Mark request as Approved.
      5. Refund is a separate step — admin uses the "Initiate Refund"
         admin action which calls process_refund_for_return().

    WHY restore_stock=True is now the only behaviour:
      A return means the item is coming back. If it's unsellable/damaged,
      admin can manually adjust inventory afterwards — but the accounting
      default must be to restore. Keeping the old optional `restore_stock`
      parameter would let admins accidentally leave stock unrestored.

    Returns: {'success': bool, 'stock_restored': bool, 'error': str}
    """
    from .models import OrderReturnRequest

    try:
        with transaction.atomic():
            req = (
                OrderReturnRequest.objects
                .select_for_update()
                .select_related('order')
                .get(pk=return_request_id)
            )

            if req.status not in ('Pending',):
                return {
                    'success': False,
                    'error': f"Return request is already '{req.status}'.",
                }

            # ── Re-lock the Order row for stock operations ────────────────────
            from .models import Order
            order = Order.objects.select_for_update().get(pk=req.order_id)

            # ── Restore stock (with per-request guard) ────────────────────────
            actually_restored = _do_restore_stock(order, req=req)

            # ── Approve ───────────────────────────────────────────────────────
            req.status = 'Approved'
            req.approved_at = timezone.now()
            req.save(update_fields=['status', 'approved_at', 'stock_restored'])

        logger.info(
            "Return request #%s approved. Stock restored: %s",
            req.id, actually_restored,
        )
        return {'success': True, 'stock_restored': actually_restored}

    except OrderReturnRequest.DoesNotExist:
        return {'success': False, 'error': 'Return request not found.'}
    except Exception as exc:
        logger.error("approve_return_request failed: %s", exc)
        return {'success': False, 'error': str(exc)}


# ─────────────────────────────────────────────────────────────────────────────
# REFUND FOR APPROVED RETURN  (admin-triggered, separate step, NO stock change)
# ─────────────────────────────────────────────────────────────────────────────

def process_refund_for_return(return_request_id: int) -> dict:
    """
    Initiate Razorpay refund after an OrderReturnRequest has been Approved.
    Marks the request as Completed.

    IMPORTANT: This function does NOT touch stock. Stock was already restored
    in approve_return_request(). Doing it again here would double-restore.

    Delegates to payments.services.initiate_refund for the actual Razorpay call.
    """
    from .models import OrderReturnRequest
    from payments.services import initiate_refund

    try:
        req = OrderReturnRequest.objects.select_related('order').get(pk=return_request_id)
    except OrderReturnRequest.DoesNotExist:
        return {'success': False, 'error': 'Return request not found.'}

    if req.status != 'Approved':
        return {
            'success': False,
            'error': (
                f"Return must be Approved before processing refund. "
                f"Current status: {req.status}"
            ),
        }

    if req.refund_initiated:
        return {'success': False, 'error': 'Refund already initiated for this return.'}

    # restore_stock=False — stock was already handled at approval time
    result = initiate_refund(req.order, restore_stock=False)

    if result['success']:
        with transaction.atomic():
            req = OrderReturnRequest.objects.select_for_update().get(pk=return_request_id)
            req.refund_initiated = True
            req.razorpay_refund_id = result.get('refund_id', '')
            req.status = 'Completed'
            req.save(update_fields=['refund_initiated', 'razorpay_refund_id', 'status'])

        logger.info("Refund processed for return request #%s", return_request_id)
    else:
        logger.error(
            "Refund failed for return request #%s: %s",
            return_request_id, result.get('error'),
        )

    return result