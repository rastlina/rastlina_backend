"""
orders/views.py
Rastlina — Order views.

Key architecture decisions:
  - CheckoutView: single atomic transaction covers ALL stock validation + order creation.
    Razorpay order creation happens OUTSIDE the transaction (network call).
    If Razorpay fails, order is created but has no razorpay_order_id — frontend
    can retry payment. This is safer than rolling back the order.

  - No COD support.

  - Coupon uses_count and exchange code are NOT consumed here (checkout).
    They are consumed at payment capture time in payments/services.py.

  - Pending orders are excluded from the authenticated user's order list.

  - GuestOrderTrackView: verifies order_id + phone OR email to prevent enumeration.
"""

import logging
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from store.models import Coupon, Product, ProductVariant, SiteConfig
from store.promotions import quote_promotions
from .models import ExchangeCode, Order, OrderItem, OrderReturnRequest, ReturnRequest
from .serializers import (
    OrderSerializer,
    OrderTrackingSerializer,
    OrderReturnRequestSerializer,
    ReturnRequestSerializer,
)
from .services import cancel_order

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# PAGINATION
# ─────────────────────────────────────────────────────────────────────────────

class OrderPagination(PageNumberPagination):
    page_size = 5
    page_size_query_param = 'page_size'
    max_page_size = 20


# ─────────────────────────────────────────────────────────────────────────────
# ORDER LIST  (authenticated users only — Pending orders excluded)
# ─────────────────────────────────────────────────────────────────────────────

class OrderListView(generics.ListAPIView):
    """
    GET /api/orders/
    Returns paginated order history for the logged-in user.
    Excludes Pending orders (pre-payment drafts).
    """
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = OrderPagination

    def get_queryset(self):
        return (
            Order.objects
            .filter(user=self.request.user)
            .exclude(order_status='Pending')
            .prefetch_related(
                'items',
                'return_requests__exchange_code',
                'order_return_requests',
            )
            .order_by('-created_at')
        )


# ─────────────────────────────────────────────────────────────────────────────
# ORDER DETAIL  (authenticated)
# ─────────────────────────────────────────────────────────────────────────────

@api_view(['GET'])
@permission_classes([IsAuthenticated])
def order_detail(request, pk):
    try:
        order = (
            Order.objects
            .prefetch_related(
                'items',
                'return_requests__exchange_code',
                'order_return_requests',
            )
            .get(pk=pk, user=request.user)
        )
        return Response(OrderSerializer(order).data)
    except Order.DoesNotExist:
        return Response({'error': 'Order not found'}, status=404)


# ─────────────────────────────────────────────────────────────────────────────
# CHECKOUT
# ─────────────────────────────────────────────────────────────────────────────

class CheckoutView(APIView):
    """
    POST /api/orders/checkout/

    Online payment only — no COD.
    """
    permission_classes = [AllowAny]  # supports both guest and authenticated

    def post(self, request):
        data = request.data
        cart_items = data.get('items', [])
        coupon_code = data.get('coupon_code', '').strip().upper()
        exchange_code_input = data.get('exchange_code', '').strip().upper()
        accepted_return_policy = data.get('accepted_return_policy', False)
        save_as_default = data.get('save_as_default', False)

        if not cart_items:
            return Response({'error': 'Cart is empty'}, status=status.HTTP_400_BAD_REQUEST)

        # ── Shipping address ──────────────────────────────────────────────────
        first_name = str(data.get('first_name') or '').strip()
        last_name = str(data.get('last_name') or '').strip()
        phone = str(data.get('phone') or '').strip()
        address = str(data.get('address') or '').strip()
        apartment = str(data.get('apartment') or '').strip()
        landmark = str(data.get('landmark') or '').strip()
        city = str(data.get('city') or '').strip()
        state = str(data.get('state') or '').strip()
        zip_code = str(data.get('zip_code') or '').strip()
        country = str(data.get('country') or 'India').strip()
        guest_email = str(data.get('email') or '').strip()

        if not all([address, city, state, zip_code]):
            return Response(
                {'error': 'Please provide a complete delivery address (address, city, state, zip_code).'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Site config ───────────────────────────────────────────────────────
        config = SiteConfig.objects.first()
        shipping_flat = Decimal(str(config.shipping_fee)) if config else Decimal('0')
        free_threshold = Decimal(str(config.free_shipping_threshold)) if config else Decimal('0')
        tax_pct = Decimal(str(config.tax_percentage)) if config else Decimal('0')

        order_email = ''
        if request.user and request.user.is_authenticated:
            order_email = request.user.email
        elif guest_email:
            order_email = guest_email

        # ── Single atomic transaction: validate + create order ────────────────
        try:
            with transaction.atomic():

                # ── Step 1: Validate all cart items (with row locks) ──────────
                order_line_items = []
                subtotal = Decimal('0.00')

                for item in cart_items:
                    variant_id = item.get('variant_id')
                    product_id = item.get('product_id')
                    quantity = int(item.get('quantity', 1))

                    if quantity < 1:
                        return Response(
                            {'error': 'Quantity must be at least 1.'},
                            status=status.HTTP_400_BAD_REQUEST,
                        )

                    if variant_id:
                        try:
                            # POSTGRES COMPATIBILITY FIX: Lock ONLY the ProductVariant row.
                            # Using select_for_update() with select_related on fields that can be Null
                            # generates a SQL LEFT OUTER JOIN. Postgres throws a runtime error if you try
                            # to lock rows across a nullable outer join without defining 'of'.
                            variant = (
                                ProductVariant.objects
                                .select_for_update(of=('self',))
                                .select_related('product', 'size', 'color')
                                .get(id=variant_id)
                            )
                        except ProductVariant.DoesNotExist:
                            return Response(
                                {'error': f'Product variant {variant_id} not found.'},
                                status=status.HTTP_400_BAD_REQUEST,
                            )

                        product = variant.product
                        server_price = (
                            Decimal(str(product.price)) +
                            Decimal(str(variant.price_override or 0))
                        )

                        size_name = variant.size.name if variant.size else ''
                        color_name = variant.color.name if variant.color else ''
                        variant_label = ' / '.join(filter(None, [size_name, color_name]))

                        if variant.stock < quantity:
                            return Response(
                                {
                                    'error': (
                                        f'Insufficient stock for "{product.name}"'
                                        + (f' ({variant_label})' if variant_label else '')
                                        + f'. Available: {variant.stock}.'
                                    )
                                },
                                status=status.HTTP_400_BAD_REQUEST,
                            )
                    else:
                        try:
                            # POSTGRES COMPATIBILITY FIX: Lock raw product row explicitly when no variants exist
                            product = (
                                Product.objects
                                .select_for_update(of=('self',))
                                .get(id=product_id, is_active=True)
                            )
                        except Product.DoesNotExist:
                            return Response(
                                {'error': f'Product {product_id} not found.'},
                                status=status.HTTP_400_BAD_REQUEST,
                            )
                        variant = None
                        server_price = Decimal(str(product.price))
                        variant_label = ''

                    subtotal += server_price * quantity

                    color_id = variant.color_id if variant and variant.color else None
                    if color_id:
                        primary_img = (
                            product.images
                            .filter(color_id=color_id, is_primary=True)
                            .first()
                            or product.images.filter(color_id=color_id).first()
                        )
                    else:
                        primary_img = (
                            product.images.filter(is_primary=True).first()
                            or product.images.first()
                        )

                    img_url = ''
                    if primary_img:
                        try:
                            img_url = request.build_absolute_uri(primary_img.image.url)
                        except Exception:
                            img_url = str(primary_img.image) if primary_img.image else ''

                    order_line_items.append({
                        'product': product,
                        'variant': variant,
                        'product_name': product.name,
                        'variant_label': variant_label,
                        'price': server_price,
                        'quantity': quantity,
                        'image_url': img_url,
                    })

                # Quote and checkout use the same server-side promotion engine.
                promotion_quote = quote_promotions(subtotal, coupon_code, user=request.user,
                    config=config, include_automatic=data.get('promotion_policy_version') == 2)
                discount_amount = Decimal(promotion_quote['coupon_discount'])

                # ── Step 3: Validate exchange code (read-only) ────────────────
                exchange_discount = Decimal('0.00')
                if exchange_code_input:
                    try:
                        exchange_obj = ExchangeCode.objects.get(code=exchange_code_input, is_used=False)
                        if exchange_obj.expires_at and exchange_obj.expires_at < timezone.now():
                            return Response({'error': 'Exchange code has expired.'}, status=400)
                        if subtotal < exchange_obj.original_order_value:
                            return Response(
                                {'error': f'New order must be at least ₹{exchange_obj.original_order_value} to use this code.'},
                                status=400,
                            )
                        exchange_discount = exchange_obj.original_order_value
                    except ExchangeCode.DoesNotExist:
                        return Response({'error': 'Invalid or already used exchange code.'}, status=400)

                # ── Step 4: Calculate fees ────────────────────────────────────
                taxable = max(Decimal('0'), subtotal - discount_amount - exchange_discount)
                tax_amount = (taxable * tax_pct) / 100

                shipping_fee = Decimal(promotion_quote['shipping_fee'])
                tax_amount = tax_amount.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
                total_amount = (taxable + tax_amount + shipping_fee).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

                # ── Step 5: Create Order ───────────────────────────────────────
                order = Order.objects.create(
                    user=request.user if request.user.is_authenticated else None,
                    first_name=first_name,
                    last_name=last_name,
                    phone=phone,
                    email=order_email,
                    shipping_address=address,
                    apartment=apartment,
                    landmark=landmark,
                    city=city,
                    state=state,
                    zip_code=zip_code,
                    country=country,
                    subtotal=subtotal,
                    discount_amount=discount_amount + exchange_discount,
                    shipping_fee=shipping_fee,
                    cod_fee=Decimal('0.00'),
                    tax_amount=tax_amount,
                    total_amount=total_amount,
                    coupon_code=coupon_code,
                    applied_discounts=promotion_quote['applied_discounts'],
                    exchange_code_used=exchange_code_input,
                    payment_method='Online',
                    payment_status='Pending',
                    order_status='Pending',
                    accepted_return_policy=accepted_return_policy,
                    stock_deducted=False,
                    stock_restored=False,
                    coupon_applied=False,
                    exchange_consumed=False,
                )

                # ── Step 6: Create OrderItems ──────────────────────────────────
                for line in order_line_items:
                    OrderItem.objects.create(
                        order=order,
                        product=line['product'],
                        variant=line['variant'],
                        product_name=line['product_name'],
                        variant_label=line['variant_label'],
                        price=line['price'],
                        quantity=line['quantity'],
                        image_url=line['image_url'],
                    )

                # ── Step 7: Optionally save address for logged-in users ────────
                if save_as_default and request.user and request.user.is_authenticated:
                    from accounts.models import SavedAddress
                    SavedAddress.objects.filter(user=request.user, is_default=True).update(is_default=False)
                    SavedAddress.objects.create(
                        user=request.user,
                        label='Home',
                        first_name=first_name,
                        last_name=last_name,
                        address=address,
                        apartment=apartment,
                        landmark=landmark,
                        city=city,
                        state=state,
                        zip_code=zip_code,
                        country=country,
                        phone=phone,
                        is_default=True,
                    )

        except ValueError as ve:
            logger.error("Checkout validation error: %s", ve)
            return Response({'error': str(ve)}, status=status.HTTP_400_BAD_REQUEST)
        except Exception as exc:
            logger.exception("Checkout failed unexpectedly: %s", exc)
            return Response(
                {'error': 'Order creation failed. Please try again.'},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        # Fully covered creator orders do not need a fake ₹1 payment.
        if total_amount == 0:
            from payments.services import complete_zero_total_order
            try:
                complete_zero_total_order(order.id)
            except ValueError as error:
                return Response({'error': str(error)}, status=400)
            return Response({'order_id': order.id, 'payment_required': False, 'amount': 0,
                             'currency': 'INR', 'applied_discounts': order.applied_discounts}, status=201)

        # ── Step 8: Create Razorpay order (OUTSIDE atomic block) ─────────────
        try:
            from payments.razorpay_client import create_order as razorpay_create_order
            rzp_order = razorpay_create_order(total_amount)
            order.razorpay_order_id = rzp_order['id']
            # Safely save with update_fields to preserve transaction states
            order.save(update_fields=['razorpay_order_id'])
        except Exception as rzp_exc:
            logger.error(
                "Razorpay order creation failed for order #%s: %s", order.id, rzp_exc
            )
            return Response(
                {
                    'error': 'Payment gateway unavailable. Please try again.',
                    'order_id': order.id,
                },
                status=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return Response(
            {
                'order_id': order.id,
                'payment_required': True,
                'applied_discounts': order.applied_discounts,
                'razorpay_order_id': rzp_order['id'],
                'amount': rzp_order['amount'],
                'currency': rzp_order.get('currency', 'INR'),
                'key': settings.RAZORPAY_KEY_ID,
                'payment_method': 'Online',
            },
            status=status.HTTP_201_CREATED,
        )


# ─────────────────────────────────────────────────────────────────────────────
# CANCEL ORDER
# ─────────────────────────────────────────────────────────────────────────────

class CancelOrderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            order = Order.objects.get(pk=pk, user=request.user)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found.'}, status=404)

        result = cancel_order(order)

        if result['success']:
            return Response(result, status=status.HTTP_200_OK)
        return Response({'error': result['error']}, status=status.HTTP_400_BAD_REQUEST)


# ─────────────────────────────────────────────────────────────────────────────
# EXCHANGE REQUEST  (defective item → exchange code)
# ─────────────────────────────────────────────────────────────────────────────

class ReturnRequestCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id, user=request.user)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found.'}, status=404)

        if order.order_status != 'Delivered':
            return Response({'error': 'Only delivered orders can have exchange requests.'}, status=400)
        if not order.accepted_return_policy:
            return Response({'error': 'Return policy was not accepted at checkout.'}, status=400)
        if not order.delivered_at:
            return Response({'error': 'Delivery date not confirmed yet. Please contact support.'}, status=400)
        if (timezone.now() - order.delivered_at).days > 15:
            return Response({'error': '15-day exchange window has expired.'}, status=400)
        if order.return_requests.filter(status__in=('Pending', 'Approved')).exists():
            return Response({'error': 'An exchange request is already pending or approved.'}, status=400)

        serializer = ReturnRequestSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(order=order, user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=400)


# ─────────────────────────────────────────────────────────────────────────────
# PHYSICAL RETURN REQUEST
# ─────────────────────────────────────────────────────────────────────────────

class OrderReturnRequestCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id, user=request.user)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found.'}, status=404)

        if order.order_status != 'Delivered':
            return Response({'error': 'Only delivered orders can be returned.'}, status=400)
        if not order.delivered_at:
            return Response({'error': 'Delivery date not confirmed.'}, status=400)
        if (timezone.now() - order.delivered_at).days > 15:
            return Response({'error': '15-day return window has expired.'}, status=400)
        if order.order_return_requests.filter(status__in=('Pending', 'Approved', 'Completed')).exists():
            return Response({'error': 'A return request is already active for this order.'}, status=400)

        serializer = OrderReturnRequestSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(order=order, user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=400)


# ─────────────────────────────────────────────────────────────────────────────
# EXCHANGE CODE VALIDATION
# ─────────────────────────────────────────────────────────────────────────────

class ValidateExchangeCodeView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        code = request.data.get('code', '').strip().upper()
        if not code:
            return Response({'valid': False, 'error': 'Code is required.'}, status=400)

        try:
            exchange = ExchangeCode.objects.get(code=code, is_used=False)
            if exchange.expires_at and exchange.expires_at < timezone.now():
                return Response({'valid': False, 'error': 'Exchange code has expired.'}, status=400)
            return Response({
                'valid': True,
                'code': exchange.code,
                'original_order_value': float(exchange.original_order_value),
                'expires_at': exchange.expires_at,
                'message': f'Code valid! New order must be at least ₹{exchange.original_order_value}.',
            })
        except ExchangeCode.DoesNotExist:
            return Response({'valid': False, 'error': 'Invalid or already used exchange code.'}, status=400)


# ─────────────────────────────────────────────────────────────────────────────
# GUEST ORDER TRACKING
# ─────────────────────────────────────────────────────────────────────────────

class GuestOrderTrackView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        order_id = request.data.get('order_id')
        phone = request.data.get('phone', '').strip()
        email = request.data.get('email', '').strip().lower()

        if not order_id:
            return Response({'error': 'order_id is required.'}, status=400)
        if not phone and not email:
            return Response({'error': 'Please provide phone or email to track your order.'}, status=400)

        try:
            qs = Order.objects.prefetch_related('items')
            if phone:
                order = qs.get(id=order_id, phone=phone)
            else:
                order = qs.get(id=order_id, email__iexact=email)
            
            # PRODUCTION SECURITY GUARD: Exclude unsubmitted draft/pending status checkouts from enumeration
            if order.order_status == 'Pending':
                raise Order.DoesNotExist

        except Order.DoesNotExist:
            return Response(
                {'error': 'No order found with the provided details. Please check and try again.'},
                status=404,
            )

        return Response(OrderTrackingSerializer(order).data)
