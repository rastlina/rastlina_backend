"""
orders/views.py
Rastlina — complete orders views.
Supports: guest checkout, authenticated checkout, Razorpay, coupons,
          exchange codes, cancel, return requests, guest order tracking.
No COD.
"""

from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ExchangeCode, Order, OrderItem, ReturnRequest
from .serializers import (
    OrderSerializer,
    OrderTrackingSerializer,
    ReturnRequestSerializer,
)
from payments.razorpay_client import _get_client
from payments.razorpay_client import create_order as razorpay_create_order
from store.models import Coupon, Product, ProductVariant, SiteConfig


# ─────────────────────────────────────────────────────────────────────────────
# Pagination
# ─────────────────────────────────────────────────────────────────────────────

class OrderPagination(PageNumberPagination):
    page_size = 5
    page_size_query_param = 'page_size'
    max_page_size = 20


# ─────────────────────────────────────────────────────────────────────────────
# Order list (authenticated users only)
# ─────────────────────────────────────────────────────────────────────────────

class OrderListView(generics.ListAPIView):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = OrderPagination

    def get_queryset(self):
        return (
            Order.objects
            .filter(user=self.request.user)
            .prefetch_related('items', 'return_requests__exchange_code')
            .order_by('-created_at')
        )


@api_view(['GET'])
@permission_classes([IsAuthenticated])
def order_detail(request, pk):
    try:
        order = (
            Order.objects
            .prefetch_related('items', 'return_requests__exchange_code')
            .get(pk=pk, user=request.user)
        )
        return Response(OrderSerializer(order).data)
    except Order.DoesNotExist:
        return Response({'error': 'Order not found'}, status=404)


# ─────────────────────────────────────────────────────────────────────────────
# Checkout (guest + authenticated)
# ─────────────────────────────────────────────────────────────────────────────

class CheckoutView(APIView):
    """
    Accepts both authenticated and guest (unauthenticated) users.
    No COD — online payment only.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        data = request.data
        cart_items = data.get('items', [])
        payment_method = data.get('payment_method', 'Online')
        coupon_code = data.get('coupon_code', '').strip().upper()
        exchange_code_input = data.get('exchange_code', '').strip().upper()
        accepted_return_policy = data.get('accepted_return_policy', False)

        if not cart_items:
            return Response({'error': 'Cart is empty'}, status=status.HTTP_400_BAD_REQUEST)

        if payment_method != 'Online':
            return Response(
                {'error': 'Only online payment is supported'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # ── Guest info validation ─────────────────────────────────────────────
        guest_email = data.get('email', '').strip()
        guest_phone = data.get('phone', '').strip()
        if not request.user.is_authenticated:
            if not guest_email:
                return Response(
                    {'error': 'Email is required for guest checkout'},
                    status=status.HTTP_400_BAD_REQUEST,
                )
            if not guest_phone:
                return Response(
                    {'error': 'Phone number is required for guest checkout'},
                    status=status.HTTP_400_BAD_REQUEST,
                )

        # ── Site config ───────────────────────────────────────────────────────
        config = SiteConfig.objects.first()
        shipping_flat = Decimal(str(config.shipping_fee)) if config else Decimal('0')
        free_threshold = Decimal(str(config.free_shipping_threshold)) if config else Decimal('0')
        tax_pct = Decimal(str(config.tax_percentage)) if config else Decimal('0')

        # ── Validate cart & build line items ──────────────────────────────────
        order_line_items = []
        subtotal = Decimal('0.00')

        with transaction.atomic():
            for item in cart_items:
                variant_id = item.get('variant_id')
                product_id = item.get('product_id')
                quantity = int(item.get('quantity', 1))

                try:
                    if variant_id:
                        variant = ProductVariant.objects.select_for_update().get(id=variant_id)
                        product = variant.product
                        server_price = Decimal(str(product.price)) + Decimal(str(variant.price_override or 0))

                        size_name = getattr(variant.size, 'name', '') if variant.size else ''
                        color_name = getattr(variant.color, 'name', '') if variant.color else ''
                        variant_label = ' / '.join(filter(None, [size_name, color_name]))

                        if variant.stock < quantity:
                            return Response(
                                {'error': f'Insufficient stock for {product.name}'
                                          + (f' ({variant_label})' if variant_label else '')},
                                status=status.HTTP_400_BAD_REQUEST,
                            )
                    else:
                        product = Product.objects.select_for_update().get(id=product_id)
                        variant = None
                        server_price = Decimal(str(product.price))
                        variant_label = ''

                    subtotal += server_price * quantity

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

                except ProductVariant.DoesNotExist:
                    return Response({'error': 'Product variant not found'}, status=status.HTTP_400_BAD_REQUEST)
                except Product.DoesNotExist:
                    return Response({'error': 'Product not found'}, status=status.HTTP_400_BAD_REQUEST)

        # ── Coupon ────────────────────────────────────────────────────────────
        discount_amount = Decimal('0.00')
        coupon_obj = None

        if coupon_code:
            try:
                coupon = Coupon.objects.get(code=coupon_code, active=True)
                now = timezone.now()
                if coupon.valid_from > now or coupon.valid_to < now:
                    return Response({'error': 'Coupon has expired'}, status=status.HTTP_400_BAD_REQUEST)
                if coupon.uses_count >= coupon.usage_limit:
                    return Response({'error': 'Coupon usage limit reached'}, status=status.HTTP_400_BAD_REQUEST)
                if subtotal < coupon.min_order_value:
                    return Response(
                        {'error': f'Minimum order of ₹{coupon.min_order_value} required for this coupon'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                if coupon.discount_type == 'percentage':
                    discount_amount = (subtotal * coupon.value) / 100
                else:
                    discount_amount = min(coupon.value, subtotal)
                coupon_obj = coupon
            except Coupon.DoesNotExist:
                return Response({'error': 'Invalid coupon code'}, status=status.HTTP_400_BAD_REQUEST)

        # ── Exchange code ─────────────────────────────────────────────────────
        exchange_obj = None
        exchange_discount = Decimal('0.00')

        if exchange_code_input:
            try:
                exchange_obj = ExchangeCode.objects.get(code=exchange_code_input, is_used=False)
                if exchange_obj.expires_at and exchange_obj.expires_at < timezone.now():
                    return Response({'error': 'Exchange code has expired'}, status=status.HTTP_400_BAD_REQUEST)
                if subtotal < exchange_obj.original_order_value:
                    return Response(
                        {'error': f'New order must be at least ₹{exchange_obj.original_order_value} to use this code'},
                        status=status.HTTP_400_BAD_REQUEST,
                    )
                exchange_discount = exchange_obj.original_order_value
            except ExchangeCode.DoesNotExist:
                return Response({'error': 'Invalid or already used exchange code'}, status=status.HTTP_400_BAD_REQUEST)

        # ── Fee calculations ──────────────────────────────────────────────────
        taxable = max(Decimal('0'), subtotal - discount_amount - exchange_discount)
        tax_amount = (taxable * tax_pct) / 100

        if free_threshold > 0 and subtotal >= free_threshold:
            shipping_fee = Decimal('0.00')
        else:
            shipping_fee = shipping_flat

        cod_fee = Decimal('0.00')
        total_amount = taxable + tax_amount + shipping_fee

        # ── Shipping address ──────────────────────────────────────────────────
        first_name = data.get('first_name', '').strip()
        last_name = data.get('last_name', '').strip()
        phone = data.get('phone', '').strip()
        email = data.get('email', '').strip()
        address = data.get('address', '').strip()
        apartment = data.get('apartment', '').strip()
        landmark = data.get('landmark', '').strip()
        city = data.get('city', '').strip()
        state = data.get('state', '').strip()
        zip_code = data.get('zip_code', '').strip()
        country = data.get('country', 'India').strip()

        if not address or not city or not state or not zip_code:
            return Response(
                {'error': 'Please provide a complete delivery address'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # For authenticated users, fall back to account email
        if request.user.is_authenticated and not email:
            email = request.user.email

        # ── Create order atomically ───────────────────────────────────────────
        try:
            with transaction.atomic():
                order = Order.objects.create(
                    user=request.user if request.user.is_authenticated else None,
                    first_name=first_name,
                    last_name=last_name,
                    phone=phone,
                    email=email,
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
                    cod_fee=cod_fee,
                    tax_amount=tax_amount,
                    total_amount=total_amount,
                    coupon_code=coupon_code,
                    exchange_code_used=exchange_code_input,
                    payment_method='Online',
                    payment_status='Pending',
                    order_status='Pending',
                    accepted_return_policy=accepted_return_policy,
                )

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

                if coupon_obj:
                    coupon_obj.uses_count += 1
                    coupon_obj.save()

                if exchange_obj:
                    exchange_obj.is_used = True
                    exchange_obj.used_at = timezone.now()
                    exchange_obj.save()

                rzp_order = razorpay_create_order(total_amount)
                order.razorpay_order_id = rzp_order['id']
                order.save(update_fields=['razorpay_order_id'])

                return Response({
                    'order_id': order.id,
                    'razorpay_order_id': rzp_order['id'],
                    'amount': rzp_order['amount'],
                    'currency': 'INR',
                    'key': settings.RAZORPAY_KEY_ID,
                    'payment_method': 'Online',
                    # Guest tracking hint
                    'guest_tracking': not request.user.is_authenticated,
                }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ─────────────────────────────────────────────────────────────────────────────
# Cancel order
# ─────────────────────────────────────────────────────────────────────────────

class CancelOrderView(APIView):
    permission_classes = [IsAuthenticated]

    @transaction.atomic
    def post(self, request, pk):
        try:
            order = Order.objects.select_for_update().get(pk=pk, user=request.user)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=404)

        if order.order_status not in ('Pending', 'Processing'):
            return Response(
                {'error': f'Cannot cancel an order that is already {order.order_status}'},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Restore variant stock
        for item in order.items.select_related('variant').all():
            if item.variant:
                item.variant.stock += item.quantity
                item.variant.save()

        refund_initiated = False
        if order.payment_status == 'Paid' and order.razorpay_payment_id:
            try:
                client = _get_client()
                amount_paise = int(order.total_amount * 100)
                client.payment.refund(order.razorpay_payment_id, {'amount': amount_paise})
                order.payment_status = 'Refunded'
                refund_initiated = True
            except Exception:
                order.payment_status = 'Refund Pending'

        order.order_status = 'Cancelled'
        order.save()

        return Response({
            'message': 'Order cancelled successfully.',
            'refund_initiated': refund_initiated,
            'note': (
                'Refund will reflect in 5–7 business days.' if refund_initiated else
                'Refund could not be processed automatically. Please contact support.'
                if order.payment_status == 'Refund Pending' else
                'No payment was made — no refund needed.'
            ),
        })


# ─────────────────────────────────────────────────────────────────────────────
# Return request (authenticated users)
# ─────────────────────────────────────────────────────────────────────────────

class ReturnRequestCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id, user=request.user)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=404)

        if order.order_status != 'Delivered':
            return Response({'error': 'Only delivered orders can have exchange requests'}, status=400)
        if not order.accepted_return_policy:
            return Response({'error': 'Return policy was not accepted at checkout'}, status=400)
        if not order.delivered_at:
            return Response({'error': 'Order delivery date not confirmed yet'}, status=400)
        if (timezone.now() - order.delivered_at).days > 15:
            return Response({'error': 'Exchange window of 15 days has expired'}, status=400)
        if order.return_requests.filter(status='Pending').exists():
            return Response({'error': 'An exchange request is already pending for this order'}, status=400)

        serializer = ReturnRequestSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(order=order, user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=400)


# ─────────────────────────────────────────────────────────────────────────────
# Validate exchange code
# ─────────────────────────────────────────────────────────────────────────────

class ValidateExchangeCodeView(APIView):
    permission_classes = [AllowAny]

    def post(self, request):
        code = request.data.get('code', '').strip().upper()
        try:
            exchange = ExchangeCode.objects.get(code=code, is_used=False)
            if exchange.expires_at and exchange.expires_at < timezone.now():
                return Response({'valid': False, 'error': 'Exchange code has expired'}, status=400)
            return Response({
                'valid': True,
                'code': exchange.code,
                'original_order_value': float(exchange.original_order_value),
                'message': f'Code valid! New order minimum: ₹{exchange.original_order_value}',
            })
        except ExchangeCode.DoesNotExist:
            return Response({'valid': False, 'error': 'Invalid or already used exchange code'}, status=400)


# ─────────────────────────────────────────────────────────────────────────────
# Guest order tracking
# ─────────────────────────────────────────────────────────────────────────────

class GuestOrderTrackView(APIView):
    """
    POST /api/orders/track/
    Body: { "order_id": 1234, "phone": "9876543210" }
      OR  { "order_id": 1234, "email": "user@example.com" }
    Returns order details + items + timeline — no auth required.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        order_id = request.data.get('order_id')
        phone = request.data.get('phone', '').strip()
        email = request.data.get('email', '').strip().lower()

        if not order_id:
            return Response({'error': 'order_id is required'}, status=400)
        if not phone and not email:
            return Response({'error': 'Provide phone or email to track your order'}, status=400)

        try:
            qs = Order.objects.prefetch_related('items').filter(id=order_id)
            if phone:
                order = qs.get(phone=phone)
            else:
                order = qs.get(email__iexact=email)
        except Order.DoesNotExist:
            return Response(
                {'error': 'No order found. Check your order ID and contact details.'},
                status=404,
            )

        return Response(OrderTrackingSerializer(order).data)