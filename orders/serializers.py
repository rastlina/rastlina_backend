"""
orders/serializers.py
Rastlina — serializers for all order-related models.
"""

from django.utils import timezone
from rest_framework import serializers

from .models import ExchangeCode, Order, OrderItem, OrderReturnRequest, ReturnRequest


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
    """Serializer for ExchangeRequest (model class: ReturnRequest)."""
    exchange_code = ExchangeCodeSerializer(read_only=True)

    class Meta:
        model = ReturnRequest
        fields = [
            'id', 'request_type', 'defect_description', 'defect_video_url',
            'status', 'admin_notes', 'exchange_code', 'created_at',
        ]
        read_only_fields = ['status', 'admin_notes', 'exchange_code', 'created_at']

    def validate_request_type(self, value):
        # Force to Exchange — Upgrade option removed
        return 'Exchange'


class OrderReturnRequestSerializer(serializers.ModelSerializer):
    """Serializer for new physical OrderReturnRequest."""

    class Meta:
        model = OrderReturnRequest
        fields = [
            'id', 'reason', 'video_url',
            'status', 'admin_notes',
            'refund_initiated', 'razorpay_refund_id',
            'created_at',
        ]
        read_only_fields = [
            'status', 'admin_notes',
            'refund_initiated', 'razorpay_refund_id', 'created_at',
        ]


class OrderSerializer(serializers.ModelSerializer):
    items = OrderItemSerializer(many=True, read_only=True)
    return_requests = ReturnRequestSerializer(many=True, read_only=True)
    order_return_requests = OrderReturnRequestSerializer(many=True, read_only=True)
    can_request_exchange = serializers.SerializerMethodField()
    can_request_return = serializers.SerializerMethodField()
    can_cancel = serializers.SerializerMethodField()
    # Legacy alias so frontend field name stays consistent
    can_request_return_legacy = serializers.SerializerMethodField()

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
            'items', 'return_requests', 'order_return_requests',
            'can_request_exchange', 'can_request_return', 'can_cancel',
            # keep old field name pointing at can_request_exchange for safety
            'can_request_return_legacy',
        ]

    def _within_window(self, obj) -> bool:
        if obj.order_status != 'Delivered':
            return False
        if not obj.accepted_return_policy:
            return False
        if not obj.delivered_at:
            return False
        if (timezone.now() - obj.delivered_at).days > 15:
            return False
        return True

    def get_can_request_exchange(self, obj):
        if not self._within_window(obj):
            return False

        if obj.payment_status == "Refunded":
            return False

        # ❌ if return/refund already exists → block exchange
        if obj.order_return_requests.filter(
            status__in=["Pending", "Approved", "Completed"]
        ).exists():
            return False

        # ❌ existing exchange request
        if obj.return_requests.filter(status__in=["Pending", "Approved"]).exists():
            return False

        return True

    def get_can_request_return(self, obj):
    # 1. Must be within return window
        if not self._within_window(obj):
            return False

        # 2. ❌ Already refunded or closed order
        if obj.payment_status == "Refunded":
            return False

        if obj.order_return_requests.filter(status="Completed").exists():
            return False

        # 3. ❌ If return already pending/approved (one active return only)
        if obj.order_return_requests.filter(
            status__in=["Pending", "Approved"]
        ).exists():
            return False

        # 4. ❌ If exchange already exists (avoid conflict between flows)
        if obj.return_requests.filter(
            status__in=["Pending", "Approved"]
        ).exists():
            return False

        return True

    def get_can_request_return_legacy(self, obj):
        """Alias kept so existing frontend can_request_return checks still work."""
        return self.get_can_request_exchange(obj)

    def get_can_cancel(self, obj):
        return obj.order_status in ('Pending', 'Processing', 'Confirmed')


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
