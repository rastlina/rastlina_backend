"""
payments/serializers.py
Rastlina — Payment serializers.
"""

from rest_framework import serializers

from .models import PaymentLog


class PaymentVerifySerializer(serializers.Serializer):
    razorpay_order_id = serializers.CharField()
    razorpay_payment_id = serializers.CharField()
    razorpay_signature = serializers.CharField()


class PaymentLogSerializer(serializers.ModelSerializer):
    amount_rupees = serializers.ReadOnlyField()

    class Meta:
        model = PaymentLog
        fields = [
            'id', 'order', 'razorpay_order_id', 'razorpay_payment_id',
            'razorpay_refund_id', 'event', 'source', 'amount_paise',
            'amount_rupees', 'currency', 'success', 'error_code',
            'error_description', 'created_at',
        ]
        read_only_fields = fields