"""Authoritative, non-compounding promotion calculation shared by quote and checkout."""
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from django.db.models import F
from django.utils import timezone
from .models import Coupon

POLICY_VERSION = 2
PENNY = Decimal('0.01')
ZERO = Decimal('0.00')


def money(value):
    try:
        amount = Decimal(str(value))
        if not amount.is_finite() or amount < 0:
            raise ValueError('Order value must be a non-negative amount.')
        return amount.quantize(PENNY, rounding=ROUND_HALF_UP)
    except (InvalidOperation, TypeError):
        raise ValueError('Order value must be a valid amount.')


def can_use_private_coupon(coupon, user=None):
    """An email allowlist takes precedence over staff status, with no staff bypass."""
    authenticated = (getattr(user, 'is_authenticated', False)
                     and getattr(user, 'is_active', False))
    if coupon.code.strip().upper() == 'INFLU' or coupon.allowed_emails:
        allowed = coupon.allowed_emails
        if not isinstance(allowed, list) or not allowed or not all(isinstance(email, str) for email in allowed):
            return False
        email = str(getattr(user, 'email', '')).strip().casefold()
        return bool(authenticated and email and email in {value.strip().casefold() for value in allowed})
    return not coupon.staff_only or bool(authenticated and getattr(user, 'is_staff', False))


def eligible_coupons(user=None):
    now = timezone.now()
    coupons = Coupon.objects.filter(active=True, valid_from__lte=now,
                                    valid_to__gte=now, uses_count__lt=F('usage_limit'))
    allowed_ids = [coupon.pk for coupon in coupons if can_use_private_coupon(coupon, user)]
    return coupons.filter(pk__in=allowed_ids)


def check_coupon(code, subtotal, user=None):
    try:
        coupon = Coupon.objects.get(code__iexact=code.strip())
    except Coupon.DoesNotExist:
        raise ValueError('Invalid promo code.')
    if not can_use_private_coupon(coupon, user):
        raise ValueError('This private promo code is available only to its authorised accounts. Sign in with an authorised account.')
    if not coupon.is_valid():
        raise ValueError('Promo code has expired, is inactive, or has reached its usage limit.')
    if subtotal < coupon.min_order_value:
        raise ValueError(f'Minimum order of ₹{coupon.min_order_value:.2f} required for {coupon.code}.')
    return coupon


def discount_for(coupon, subtotal):
    amount = subtotal * coupon.value / Decimal('100') if coupon.discount_type == 'percentage' else coupon.value
    return min(subtotal, max(ZERO, amount)).quantize(PENNY, rounding=ROUND_HALF_UP)


def quote_promotions(subtotal, code='', *, user=None, config=None, include_automatic=True):
    subtotal = money(subtotal)
    shipping_flat = money(config.shipping_fee) if config else ZERO
    threshold = money(config.free_shipping_threshold) if config else ZERO
    base_shipping = ZERO if threshold > 0 and subtotal >= threshold else shipping_flat
    manual = check_coupon(code, subtotal, user) if code else None
    selected = [manual] if manual else []
    # Creator codes are exclusive. Public DIWALI10 can combine with one automatic
    # offer. Each percentage uses the ORIGINAL subtotal (10% + 10% = 20%).
    if subtotal > 0 and include_automatic and (not manual or (manual.combine_with_automatic and not manual.staff_only)):
        candidates = list(eligible_coupons(user).filter(auto_apply=True, staff_only=False,
                         free_shipping=False, min_order_value__lte=subtotal).exclude(code__iexact='INFLU'))
        if candidates:
            automatic = max(candidates, key=lambda coupon: discount_for(coupon, subtotal))
            if not any(c.pk == automatic.pk for c in selected):
                selected.append(automatic)
    discount = ZERO
    shipping_discount = ZERO
    applied = []
    for coupon in selected:
        amount = min(discount_for(coupon, subtotal), subtotal - discount)
        waiver = base_shipping if coupon.free_shipping and not shipping_discount else ZERO
        discount += amount
        shipping_discount += waiver
        applied.append({
            'code': coupon.code, 'discount_type': coupon.discount_type, 'value': str(coupon.value),
            'min_order_value': str(coupon.min_order_value), 'discount': str(amount),
            'shipping_discount': str(waiver), 'free_shipping': coupon.free_shipping,
            'auto_apply': coupon.auto_apply, 'staff_only': coupon.staff_only,
        })
    shipping = max(ZERO, base_shipping - shipping_discount)
    tax_pct = Decimal(str(config.tax_percentage)) if config else ZERO
    tax = ((subtotal - discount) * tax_pct / Decimal('100')).quantize(PENNY, rounding=ROUND_HALF_UP)
    return {
        'policy_version': POLICY_VERSION, 'subtotal': str(subtotal), 'applied_discounts': applied,
        'coupon_discount': str(discount), 'shipping_discount': str(shipping_discount),
        'shipping_fee': str(shipping), 'tax': str(tax), 'total': str(subtotal - discount + shipping + tax),
    }
