"""
orders/models.py
Rastlina — Orders, OrderItem, ExchangeCode,
           ReturnRequest (= Exchange Request, kept for DB compat),
           OrderReturnRequest (NEW — physical return / refund flow).
"""

import uuid
from datetime import timedelta

from django.conf import settings
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


class Order(models.Model):
    PAYMENT_STATUS = [
        ('Pending', 'Pending'),
        ('Paid', 'Paid'),
        ('Failed', 'Failed'),
        ('Refunded', 'Refunded'),
        ('Refund Pending', 'Refund Pending'),
    ]
    ORDER_STATUS = [
        ('Pending', 'Pending'),
        ('Processing', 'Processing'),
        ('Confirmed', 'Confirmed'),
        ('Shipped', 'Shipped'),
        ('Delivered', 'Delivered'),
        ('Cancelled', 'Cancelled'),
    ]
    PAYMENT_METHOD = [('Online', 'Online')]
    @property
    def is_refunded_or_closed(self):
        return (
            self.payment_status == "Refunded"
            or self.order_return_requests.filter(status="Completed").exists()
        )

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='orders',
    )
    first_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)

    shipping_address = models.TextField()
    apartment = models.CharField(max_length=255, blank=True)
    landmark = models.CharField(max_length=255, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=100, blank=True)
    zip_code = models.CharField(max_length=20, blank=True)
    country = models.CharField(max_length=100, default='India')

    subtotal = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    discount_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    shipping_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    cod_fee = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    tax_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0)
    total_amount = models.DecimalField(max_digits=10, decimal_places=2)
    coupon_code = models.CharField(max_length=50, blank=True)
    exchange_code_used = models.CharField(max_length=20, blank=True)

    payment_method = models.CharField(max_length=20, choices=PAYMENT_METHOD, default='Online')
    payment_status = models.CharField(max_length=20, choices=PAYMENT_STATUS, default='Pending')
    order_status = models.CharField(max_length=20, choices=ORDER_STATUS, default='Pending')

    accepted_return_policy = models.BooleanField(default=True)

    razorpay_order_id = models.CharField(max_length=100, unique=True, null=True, blank=True)
    razorpay_payment_id = models.CharField(max_length=100, null=True, blank=True)

    tracking_link = models.URLField(max_length=500, blank=True, null=True)
    tracking_note = models.TextField(blank=True, null=True)

    delivered_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        identifier = self.user.email if self.user else self.email or 'Guest'
        return f'Order #{self.id} — {identifier}'

    @property
    def customer_name(self):
        return f'{self.first_name} {self.last_name}'.strip()


class OrderItem(models.Model):
    order = models.ForeignKey(Order, related_name='items', on_delete=models.CASCADE)
    product = models.ForeignKey(
        'store.Product', on_delete=models.SET_NULL, null=True, blank=True,
    )
    variant = models.ForeignKey(
        'store.ProductVariant', on_delete=models.SET_NULL, null=True, blank=True,
    )
    product_name = models.CharField(max_length=255)
    variant_label = models.CharField(max_length=100, blank=True)
    price = models.DecimalField(max_digits=10, decimal_places=2)
    quantity = models.PositiveIntegerField(default=1)
    image_url = models.TextField(blank=True)

    def __str__(self):
        return f'{self.product_name} x{self.quantity}'

    @property
    def item_total(self):
        return self.price * self.quantity


class ExchangeCode(models.Model):
    """Auto-generated when admin approves an exchange request."""
    code = models.CharField(max_length=20, unique=True)
    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='exchange_codes')
    original_order_value = models.DecimalField(max_digits=10, decimal_places=2)
    is_used = models.BooleanField(default=False)
    used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = f'YC-{uuid.uuid4().hex[:8].upper()}'
        super().save(*args, **kwargs)

    def __str__(self):
        return f'{self.code} (Order #{self.order_id})'


class ReturnRequest(models.Model):
    """
    EXCHANGE REQUEST model (class name kept for DB/migration compatibility).
    Customer reports defective product → admin approves → ExchangeCode generated.
    Frontend shows this as "Exchange Request".
    """
    STATUS_CHOICES = [
        ('Pending', 'Pending Review'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
    ]
    TYPE_CHOICES = [
        ('Exchange', 'Exchange (Defective product replacement)'),
    ]

    order = models.ForeignKey(Order, on_delete=models.CASCADE, related_name='return_requests')
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
    )
    guest_email = models.EmailField(blank=True)

    request_type = models.CharField(max_length=20, choices=TYPE_CHOICES, default='Exchange')
    defect_description = models.TextField()
    defect_video_url = models.URLField(max_length=1000, blank=True, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    admin_notes = models.TextField(blank=True)

    exchange_code = models.OneToOneField(
        ExchangeCode, on_delete=models.SET_NULL,
        null=True, blank=True, related_name='return_request',
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Exchange Request'
        verbose_name_plural = 'Exchange Requests'

    def __str__(self):
        return f'Exchange #{self.id} — Order #{self.order_id} [{self.status}]'


@receiver(post_save, sender=ReturnRequest)
def create_exchange_code_on_approval(sender, instance, created, **kwargs):
    if instance.status == 'Approved' and not instance.exchange_code_id:
        existing = ExchangeCode.objects.filter(order=instance.order).first()
        code = existing or ExchangeCode.objects.create(
            order=instance.order,
            original_order_value=instance.order.total_amount,
            expires_at=timezone.now() + timedelta(days=30),
            notes=f'Auto-generated for exchange request #{instance.id}',
        )
        ReturnRequest.objects.filter(pk=instance.pk).update(exchange_code=code)


class OrderReturnRequest(models.Model):
    """
    NEW — Physical return request.
    Customer wants to return the product for a refund or credit.
    Admin reviews and may initiate a Razorpay refund separately.
    Frontend shows this as "Return Request".
    """
    STATUS_CHOICES = [
        ('Pending', 'Pending Review'),
        ('Approved', 'Approved — Return Accepted'),
        ('Rejected', 'Rejected'),
        ('Completed', 'Completed — Refund Processed'),
    ]

    order = models.ForeignKey(
        Order, on_delete=models.CASCADE, related_name='order_return_requests',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True,
    )
    guest_email = models.EmailField(blank=True)

    reason = models.TextField()
    video_url = models.URLField(max_length=1000, blank=True, null=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    admin_notes = models.TextField(blank=True)

    refund_initiated = models.BooleanField(default=False)
    razorpay_refund_id = models.CharField(max_length=100, blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        verbose_name = 'Order Return Request'
        verbose_name_plural = 'Order Return Requests'

    def __str__(self):
        return f'Return Request #{self.id} — Order #{self.order_id} [{self.status}]'
