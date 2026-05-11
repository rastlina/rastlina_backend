"""
orders/serializers.py
Rastlina — full serializers for Order, OrderItem, ReturnRequest, ExchangeCode.
"""

from django.utils import timezone
from rest_framework import serializers
from .models import Order, OrderItem, ReturnRequest, ExchangeCode


class OrderItemSerializer(serializers.ModelSerializer):
    product_slug = serializers.SerializerMethodField()
    item_total = serializers.SerializerMethodField()

    class Meta:
        model = OrderItem
        fields = [
            'id', 'product_name', 'product_slug',
            'variant_label', 'price', 'quantity', 'image_url', 'item_total',
        ]

    def get_product_slug(self, obj):
        return obj.product.slug if obj.product else ''

    def get_item_total(self, obj):
        return float(obj.price * obj.quantity)


class ExchangeCodeSerializer(serializers.ModelSerializer):
    class Meta:
        model = ExchangeCode
        fields = ['code', 'original_order_value', 'is_used', 'expires_at', 'notes']


class ReturnRequestSerializer(serializers.ModelSerializer):
    exchange_code = ExchangeCodeSerializer(read_only=True)

    class Meta:
        model = ReturnRequest
        fields = [
            'id', 'request_type', 'defect_description', 'defect_video_url',
            'status', 'admin_notes', 'exchange_code', 'created_at',
        ]
        read_only_fields = ['status', 'admin_notes', 'exchange_code', 'created_at']


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    return_requests = ReturnRequestSerializer(many=True, read_only=True)
    can_request_return = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = [
            'id', 'first_name', 'last_name', 'phone', 'email',
            'shipping_address', 'apartment', 'landmark',
            'city', 'state', 'zip_code', 'country',
            'subtotal', 'discount_amount', 'shipping_fee',
            'cod_fee', 'tax_amount', 'total_amount',
            'coupon_code', 'exchange_code_used',
            'payment_method', 'payment_status', 'order_status',
            'razorpay_order_id', 'tracking_link', 'tracking_note',
            'accepted_return_policy', 'delivered_at', 'created_at',
            'items', 'return_requests', 'can_request_return', 'can_cancel',
        ]

    def get_can_request_return(self, obj):
        if obj.order_status != 'Delivered':
            return False
        if not obj.accepted_return_policy:
            return False
        if not obj.delivered_at:
            return False
        if (timezone.now() - obj.delivered_at).days > 15:
            return False
        if obj.return_requests.filter(status='Pending').exists():
            return False
        return True

    def get_can_cancel(self, obj):
        return obj.order_status in ('Pending', 'Processing')


# ── Lightweight serializer for guest order tracking ───────────────────────────

class OrderTrackingSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)

    class Meta:
        model = Order
        fields = [
            'id', 'first_name', 'last_name', 'phone', 'email',
            'shipping_address', 'apartment', 'landmark',
            'city', 'state', 'zip_code', 'country',
            'subtotal', 'discount_amount', 'shipping_fee',
            'tax_amount', 'total_amount', 'coupon_code',
            'payment_method', 'payment_status', 'order_status',
            'tracking_link', 'tracking_note', 'delivered_at', 'created_at',
            'items',
        ]