from datetime import timedelta
import logging
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone
from orders.shipping_models import ShiprocketSync
from orders.shiprocket_sync import sync_paid_order

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Sync queued paid orders to Shiprocket New Orders without booking couriers.'

    def handle(self, *args, **options):
        sent = failed = 0
        ids = list(ShiprocketSync.objects.filter(status__in=['Pending', 'Error'],
                   next_attempt_at__lte=timezone.now()).values_list('pk', flat=True)[:10])
        for pk in ids:
            with transaction.atomic():
                row = ShiprocketSync.objects.select_for_update(skip_locked=True).filter(
                    pk=pk, status__in=['Pending', 'Error'], next_attempt_at__lte=timezone.now()).first()
                if not row:
                    continue
                row.attempts += 1
                if row.order.payment_status != 'Paid' or row.order.order_status in ['Cancelled', 'Shipped', 'Delivered']:
                    row.status = 'Skipped'
                    row.last_error = 'Order no longer eligible for shipping.'
                else:
                    try:
                        sync_paid_order(row.order_id)
                        row.status = 'Synced'
                        row.synced_at = timezone.now()
                        row.last_error = ''
                        sent += 1
                    except Exception as exc:
                        row.status = 'Error'
                        row.last_error = str(exc)[:255] if isinstance(exc, ValueError) else type(exc).__name__
                        row.next_attempt_at = timezone.now() + timedelta(minutes=min(60, 5 * row.attempts))
                        failed += 1
                        logger.error('Shiprocket order %s sync failed (%s)', row.order_id, type(exc).__name__)
                row.save(update_fields=['status', 'attempts', 'last_error', 'next_attempt_at', 'synced_at'])
        self.stdout.write(f'Shiprocket sync: synced={sent}, deferred={failed}')

