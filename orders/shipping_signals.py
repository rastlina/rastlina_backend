from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Order
from .shipping_models import ShiprocketSync


@receiver(post_save, sender=Order, dispatch_uid='rastlina_queue_shiprocket')
def queue_paid_order(sender, instance, raw=False, using='default', **kwargs):
    if not raw and getattr(instance, '_notify_merchant', False):
        ShiprocketSync.objects.using(using).get_or_create(order_id=instance.pk)

