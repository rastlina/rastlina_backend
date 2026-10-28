from django.db import models
from django.utils import timezone


class OrderNotification(models.Model):
    order = models.OneToOneField('orders.Order', on_delete=models.CASCADE,
                                related_name='merchant_notification')
    recipient = models.EmailField(default='info.rastlina@gmail.com')
    created_at = models.DateTimeField(auto_now_add=True)
    sent_at = models.DateTimeField(null=True, blank=True)
    attempts = models.PositiveIntegerField(default=0)
    next_attempt_at = models.DateTimeField(default=timezone.now)
    last_error = models.CharField(max_length=100, blank=True)

    class Meta:
        ordering = ['created_at']

