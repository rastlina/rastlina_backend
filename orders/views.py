"""
orders/views.py — Rastlina
Adds:
  • OrderReturnRequestCreateView  POST /api/orders/<id>/return-product/
  • OrderListView excludes Pending orders from the user-facing list
"""

from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone
from rest_framework import generics, status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.pagination import PageNumberPagination
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ExchangeCode, Order, OrderItem, OrderReturnRequest, ReturnRequest
from .serializers import (
    OrderReturnRequestSerializer,
    OrderSerializer,
    OrderTrackingSerializer,
    ReturnRequestSerializer,
)
from payments.razorpay_client import create_order as razorpay_create_order
from payments.services import cancel_order_with_refund
from store.models import Coupon, Product, ProductVariant, SiteConfig


# ─── Pagination ───────────────────────────────────────────────────────────────

class OrderPagination(PageNumberPagination):
    page_size = 5
    page_size_query_param = 'page_size'
    max_page_size = 20


# ─── Order list (authenticated, Pending excluded) ─────────────────────────────

class OrderListView(generics.ListAPIView):
    serializer_class = OrderSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = OrderPagination

    def get_queryset(self):
        return (
            Order.objects
            .filter(user=self.request.user)
            .exclude(order_status='Pending')          # hide pre-payment drafts
            .prefetch_related(
                'items',
                'return_requests__exchange_code',
                'order_return_requests',
            )
            .order_by('-created_at')
        )


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


# ─── Checkout ─────────────────────────────────────────────────────────────────

class CheckoutView(APIView):
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

        config = SiteConfig.objects.first()
        shipping_flat = Decimal(str(config.shipping_fee)) if config else Decimal('0')
        free_threshold = Decimal(str(config.free_shipping_threshold)) if config else Decimal('0')
        tax_pct = Decimal(str(config.tax_percentage)) if config else Decimal('0')

        order_line_items = []
        subtotal = Decimal('0.00')

        with transaction.atomic():
            for item in cart_items:
                variant_id = item.get('variant_id')
                product_id = item.get('product_id')
                quantity = int(item.get('quantity', 1))
                if quantity <= 0:
                    return Response({'error': 'Invalid quantity'}, status=status.HTTP_400_BAD_REQUEST)

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
                    primary_img = product.images.filter(is_primary=True).first() or product.images.first()
                    img_url = ''
                    if primary_img:
                        try:
                            img_url = request.build_absolute_uri(primary_img.image.url)
                        except Exception:
                            img_url = str(primary_img.image) if primary_img.image else ''

                    order_line_items.append({
                        'product': product, 'variant': variant,
                        'product_name': product.name, 'variant_label': variant_label,
                        'price': server_price, 'quantity': quantity, 'image_url': img_url,
                    })
                except ProductVariant.DoesNotExist:
                    return Response({'error': 'Product variant not found'}, status=status.HTTP_400_BAD_REQUEST)
                except Product.DoesNotExist:
                    return Response({'error': 'Product not found'}, status=status.HTTP_400_BAD_REQUEST)

        # Coupon
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
                discount_amount = (subtotal * coupon.value / 100) if coupon.discount_type == 'percentage' else min(coupon.value, subtotal)
                coupon_obj = coupon
            except Coupon.DoesNotExist:
                return Response({'error': 'Invalid coupon code'}, status=status.HTTP_400_BAD_REQUEST)

        # Exchange code
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

        taxable = max(Decimal('0'), subtotal - discount_amount - exchange_discount)
        tax_amount = (taxable * tax_pct) / 100
        shipping_fee = Decimal('0.00') if (free_threshold > 0 and subtotal >= free_threshold) else shipping_flat
        total_amount = taxable + tax_amount + shipping_fee

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
            return Response({'error': 'Please provide a complete delivery address'}, status=status.HTTP_400_BAD_REQUEST)

        if request.user.is_authenticated and not email:
            email = request.user.email

        try:
            with transaction.atomic():
                order = Order.objects.create(
                    user=request.user if request.user.is_authenticated else None,
                    first_name=first_name, last_name=last_name, phone=phone, email=email,
                    shipping_address=address, apartment=apartment, landmark=landmark,
                    city=city, state=state, zip_code=zip_code, country=country,
                    subtotal=subtotal, discount_amount=discount_amount + exchange_discount,
                    shipping_fee=shipping_fee, cod_fee=Decimal('0'), tax_amount=tax_amount,
                    total_amount=total_amount, coupon_code=coupon_code,
                    exchange_code_used=exchange_code_input, payment_method='Online',
                    payment_status='Pending', order_status='Pending',
                    accepted_return_policy=accepted_return_policy,
                )

                for line in order_line_items:
                    OrderItem.objects.create(
                        order=order, product=line['product'], variant=line['variant'],
                        product_name=line['product_name'], variant_label=line['variant_label'],
                        price=line['price'], quantity=line['quantity'], image_url=line['image_url'],
                    )

                if coupon_obj:
                    coupon_obj.uses_count += 1
                    coupon_obj.save(update_fields=['uses_count'])

                if exchange_obj:
                    exchange_obj.is_used = True
                    exchange_obj.used_at = timezone.now()
                    exchange_obj.save(update_fields=['is_used', 'used_at'])

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
                    'guest_tracking': not request.user.is_authenticated,
                }, status=status.HTTP_201_CREATED)

        except Exception as e:
            return Response({'error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)


# ─── Cancel order ─────────────────────────────────────────────────────────────

class CancelOrderView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        try:
            order = Order.objects.get(pk=pk, user=request.user)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=404)

        result = cancel_order_with_refund(order)
        if not result['success']:
            return Response({'error': result.get('error', 'Could not cancel order')}, status=status.HTTP_400_BAD_REQUEST)

        return Response({
            'message': 'Order cancelled successfully.',
            'refund_initiated': result.get('refund_initiated', False),
            'refund_id': result.get('refund_id'),
            'note': result.get('note', ''),
        })


# ─── Exchange Request (existing ReturnRequest model) ──────────────────────────

class ReturnRequestCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id, user=request.user)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=404)

        if order.order_status != 'Delivered':
            return Response({'error': 'Only delivered orders are eligible for exchange requests'}, status=400)
        if not order.accepted_return_policy:
            return Response({'error': 'Return policy was not accepted at checkout'}, status=400)
        if not order.delivered_at:
            return Response({'error': 'Order delivery date not confirmed yet'}, status=400)
        if (timezone.now() - order.delivered_at).days > 15:
            return Response({'error': 'Exchange window of 15 days has expired'}, status=400)
        if order.return_requests.filter(status='Pending').exists():
            return Response({'error': 'An exchange request is already pending for this order'}, status=400)

        # Force request_type to Exchange only
        mutable_data = request.data.copy() if hasattr(request.data, 'copy') else dict(request.data)
        mutable_data['request_type'] = 'Exchange'

        serializer = ReturnRequestSerializer(data=mutable_data)
        if serializer.is_valid():
            serializer.save(order=order, user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=400)


# ─── Return Request (NEW physical return model) ───────────────────────────────

class OrderReturnRequestCreateView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, order_id):
        try:
            order = Order.objects.get(id=order_id, user=request.user)
        except Order.DoesNotExist:
            return Response({'error': 'Order not found'}, status=404)

        if order.order_status != 'Delivered':
            return Response({'error': 'Only delivered orders can have return requests'}, status=400)
        if not order.delivered_at:
            return Response({'error': 'Order delivery date not confirmed yet'}, status=400)
        if (timezone.now() - order.delivered_at).days > 15:
            return Response({'error': 'Return window of 15 days has expired'}, status=400)
        if order.order_return_requests.filter(status='Pending').exists():
            return Response({'error': 'A return request is already pending for this order'}, status=400)

        serializer = OrderReturnRequestSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save(order=order, user=request.user)
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=400)


# ─── Exchange code validation ─────────────────────────────────────────────────

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
                'message': f'Code valid! Minimum new order: ₹{exchange.original_order_value}',
            })
        except ExchangeCode.DoesNotExist:
            return Response({'valid': False, 'error': 'Invalid or already used exchange code'}, status=400)


# ─── Guest order tracking ─────────────────────────────────────────────────────

class GuestOrderTrackView(APIView):
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
            order = qs.get(phone=phone) if phone else qs.get(email__iexact=email)
        except Order.DoesNotExist:
            return Response({'error': 'No order found. Check your order ID and contact details.'}, status=404)

        return Response(OrderTrackingSerializer(order).data)