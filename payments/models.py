"""
payments/models.py
Rastlina — Payment event log.
Stores every Razorpay event (captured, failed, refunded) for audit purposes.
The Order model itself holds razorpay_order_id / razorpay_payment_id as
the source of truth for payment status; this table is the audit trail.
"""

from django.db import models

from orders.models import Order


class PaymentLog(models.Model):
    """
    Immutable append-only record of every Razorpay event that touches an order.
    Do NOT update existing rows — always create a new one.
    """

    EVENT_CHOICES = [
        ('order.created', 'Order Created'),
        ('payment.captured', 'Payment Captured'),
        ('payment.failed', 'Payment Failed'),
        ('payment.refunded', 'Payment Refunded'),
        ('signature.verified', 'Signature Verified'),
        ('signature.failed', 'Signature Failed'),
        ('webhook.received', 'Webhook Received'),
        ('webhook.ignored', 'Webhook Ignored'),
    ]

    SOURCE_CHOICES = [
        ('client', 'Client Callback'),
        ('webhook', 'Razorpay Webhook'),
        ('manual', 'Manual / Admin'),
    ]

    order = models.ForeignKey(
        Order,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='payment_logs',
        help_text='Null if order could not be resolved (e.g. unknown rzp_order_id)',
    )
    razorpay_order_id = models.CharField(max_length=100, blank=True, db_index=True)
    razorpay_payment_id = models.CharField(max_length=100, blank=True, db_index=True)
    razorpay_refund_id = models.CharField(max_length=100, blank=True)
    event = models.CharField(max_length=40, choices=EVENT_CHOICES)
    source = models.CharField(max_length=20, choices=SOURCE_CHOICES, default='client')
    amount_paise = models.PositiveIntegerField(
        default=0, help_text='Amount in paise (100 paise = ₹1)',
    )
    currency = models.CharField(max_length=10, default='INR')
    success = models.BooleanField(default=True)
    error_code = models.CharField(max_length=100, blank=True)
    error_description = models.TextField(blank=True)
    raw_payload = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Payment Log'
        verbose_name_plural = 'Payment Logs'

    def __str__(self):
        return (
            f"[{self.event}] Order #{self.order_id} "
            f"| {self.razorpay_payment_id or self.razorpay_order_id} "
            f"({'ok' if self.success else 'fail'})"
        )

    @property
    def amount_rupees(self):
        return self.amount_paise / 100