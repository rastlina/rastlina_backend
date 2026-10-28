from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from .models import Order
from .notification_models import OrderNotification


@receiver(pre_save, sender=Order, dispatch_uid='rastlina_paid_order_before')
def detect_payment_transition(sender, instance, raw=False, using='default', **kwargs):
    instance._notify_merchant = False
    if raw or instance.payment_status != 'Paid':
        return
    fields = kwargs.get('update_fields')
    if fields is not None and 'payment_status' not in fields:
        return
    previous = sender.objects.using(using).filter(pk=instance.pk).values_list(
        'payment_status', flat=True).first()
    instance._notify_merchant = previous != 'Paid'


@receiver(post_save, sender=Order, dispatch_uid='rastlina_paid_order_after')
def queue_merchant_notification(sender, instance, raw=False, using='default', **kwargs):
    if not raw and getattr(instance, '_notify_merchant', False):
        # Insert into the same payment transaction: rolled-back payments never email.
        OrderNotification.objects.using(using).get_or_create(order_id=instance.pk)

