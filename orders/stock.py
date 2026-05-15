"""
orders/stock.py
Rastlina — Single source of truth for all inventory (stock) operations.

WHY THIS FILE EXISTS:
  Previously, stock logic was duplicated in two places:
    - payments/services.py  (_deduct_stock, _restore_stock)
    - orders/services.py    (deduct_stock_for_order, restore_stock_for_order)

  The two implementations also differed: payments/ handled both variant AND
  product-level stock; orders/ handled only variants. This caused silent bugs
  when products had no variant.

  This module replaces both. Every flow — payment capture, cancellation,
  exchange approval, return approval — imports from here.

PUBLIC API (the only two functions any other module should call):
  deduct_stock_for_order(order)   — called at payment capture
  restore_stock_for_order(order)  — called at cancellation / exchange / return

RULES FOR CALLERS (enforced by design, not by this module):
  1. Always call inside transaction.atomic() with the Order row already
     locked via select_for_update().
  2. Check idempotency flags BEFORE calling:
       deduct:  only if order.stock_deducted == False
       restore: only if order.stock_deducted == True
                     AND order.stock_restored == False
  3. After a successful call, set the corresponding flag and save the Order:
       deduct:  order.stock_deducted = True
       restore: order.stock_restored = True
     (The flag write and the stock write must be in the same atomic block.)

NEVER call these functions directly from views. Always go through the
service layer (payments/services.py or orders/services.py).
"""

import logging

logger = logging.getLogger(__name__)


def deduct_stock_for_order(order) -> None:
    """
    Deduct stock for every item in the order.

    Handles both variant-level and product-level stock so that products
    without variants (bare Product.stock) are also covered.

    Raises ValueError if any item has insufficient stock — the caller's
    atomic transaction will roll back automatically.

    Caller contract:
      - Must be inside transaction.atomic() with Order locked via select_for_update().
      - Must check order.stock_deducted == False before calling.
      - Must set order.stock_deducted = True and save after this returns.
    """
    for item in (
        order.items
        .select_related("variant", "variant__product", "product")
        .select_for_update()
        .all()
    ):
        if item.variant:
            variant = item.variant
            if variant.stock < item.quantity:
                raise ValueError(
                    f"Insufficient stock: variant {variant.id} ({variant}) "
                    f"has {variant.stock} unit(s) but order #{order.id} "
                    f"needs {item.quantity}. Transaction aborted."
                )
            variant.stock -= item.quantity
            variant.save(update_fields=["stock"])
            logger.debug(
                "Stock deducted — variant=%s  -%s  →  %s remaining",
                variant.id, item.quantity, variant.stock,
            )

        elif item.product:
            product = item.product
            if product.stock < item.quantity:
                raise ValueError(
                    f"Insufficient stock: product {product.id} ({product}) "
                    f"has {product.stock} unit(s) but order #{order.id} "
                    f"needs {item.quantity}. Transaction aborted."
                )
            product.stock -= item.quantity
            product.save(update_fields=["stock"])
            logger.debug(
                "Stock deducted — product=%s  -%s  →  %s remaining",
                product.id, item.quantity, product.stock,
            )

        else:
            # Snapshot-only item (product/variant deleted) — nothing to deduct
            logger.warning(
                "OrderItem %s has no live variant or product — skipping stock deduction.",
                item.id,
            )


def restore_stock_for_order(order) -> None:
    """
    Restore stock for every item in the order.

    Used by:
      - cancel_order_with_refund  (order cancelled before shipment)
      - approve_exchange_request  (customer keeps defective item; new stock freed)
      - approve_return_request    (physical return; item back in inventory)

    Handles both variant-level and product-level stock.

    Caller contract:
      - Must be inside transaction.atomic() with Order locked via select_for_update().
      - Must check order.stock_deducted == True (stock was actually taken).
      - Must check order.stock_restored == False (not already restored).
      - Must set order.stock_restored = True and save after this returns.
    """
    for item in (
        order.items
        .select_related("variant", "variant__product", "product")
        .select_for_update()
        .all()
    ):
        if item.variant:
            item.variant.stock += item.quantity
            item.variant.save(update_fields=["stock"])
            logger.debug(
                "Stock restored — variant=%s  +%s  →  %s total",
                item.variant.id, item.quantity, item.variant.stock,
            )

        elif item.product:
            item.product.stock += item.quantity
            item.product.save(update_fields=["stock"])
            logger.debug(
                "Stock restored — product=%s  +%s  →  %s total",
                item.product.id, item.quantity, item.product.stock,
            )

        else:
            logger.warning(
                "OrderItem %s has no live variant or product — skipping stock restoration.",
                item.id,
            )