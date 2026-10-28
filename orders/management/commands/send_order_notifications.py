import logging
from datetime import timedelta
from django.core.management.base import BaseCommand
from django.core.mail import EmailMessage, get_connection
from django.conf import settings
from django.db import transaction
from django.utils import timezone
from orders.notification_models import OrderNotification

logger = logging.getLogger(__name__)


def notification_body(order):
    lines = [f'New paid order #{order.pk} on www.rastlina.com', '',
             f'Customer: {order.first_name} {order.last_name}',
             f'Email: {order.email}', f'Phone: {order.phone}', '', 'Items:']
    for item in order.items.all():
        label = f' ({item.variant_label})' if item.variant_label else ''
        lines.append(f'- {item.product_name}{label} x {item.quantity}: INR {item.item_total}')
    lines += ['', f'Subtotal: INR {order.subtotal}',
              f'Discount: INR {order.discount_amount}', f'Shipping: INR {order.shipping_fee}',
              f'Tax: INR {order.tax_amount}', f'Total: INR {order.total_amount}',
              f'Payment: {order.payment_method} / {order.payment_status}',
              f'Order status: {order.order_status}', '', 'Shipping address:',
              order.shipping_address, order.apartment or '', order.landmark or '',
              f'{order.city}, {order.state} {order.zip_code}, {order.country}', '',
              f'Open order: https://admin.rastlina.com/admin/orders/order/{order.pk}/change/']
    return '\n'.join(lines)


class Command(BaseCommand):
    help = 'Deliver queued new-order merchant emails with automatic retries.'

    def handle(self, *args, **options):
        sent = failed = 0
        ids = list(OrderNotification.objects.filter(sent_at__isnull=True,
                   next_attempt_at__lte=timezone.now()).values_list('pk', flat=True)[:20])
        for pk in ids:
            with transaction.atomic():
                row = OrderNotification.objects.select_for_update(skip_locked=True).filter(
                    pk=pk, sent_at__isnull=True, next_attempt_at__lte=timezone.now()).first()
                if not row:
                    continue
                order = row.order
                row.attempts += 1
                try:
                    connection = get_connection(timeout=20, fail_silently=False)
                    msg = EmailMessage(
                        subject=f'Rastlina: New order #{order.pk} - INR {order.total_amount}',
                        body=notification_body(order), from_email=settings.DEFAULT_FROM_EMAIL,
                        to=[row.recipient], connection=connection,
                        headers={'Message-ID': f'<rastlina-order-{order.pk}@rastlina.com>'})
                    if msg.send(fail_silently=False) != 1:
                        raise RuntimeError('EmailNotAccepted')
                    row.sent_at = timezone.now()
                    row.last_error = ''
                    sent += 1
                except Exception as exc:
                    # Store only the error type; SMTP responses may contain credentials/data.
                    row.last_error = type(exc).__name__
                    row.next_attempt_at = timezone.now() + timedelta(minutes=min(60, 5 * row.attempts))
                    failed += 1
                    logger.error('Merchant notification failed for order %s (%s)', order.pk, row.last_error)
                row.save(update_fields=['attempts', 'sent_at', 'last_error', 'next_attempt_at'])
        self.stdout.write(f'Order notifications: sent={sent}, deferred={failed}')
