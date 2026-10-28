"""Upgrade the supplied production migration graph without losing shipping data."""
from datetime import timedelta
from decimal import Decimal
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase
from django.utils import timezone


class ProductionUpgradeTests(TransactionTestCase):
    def test_existing_shipping_and_video_branches_upgrade_without_data_loss(self):
        old_targets = [('orders', '0007_shiprocket_sync'), ('store', '0010_merge_watchandshop_mp4')]
        latest_targets = [('orders', '0008_merge_promotions_shipping'), ('store', '0011_merge_promotions_watch_shop')]
        executor = MigrationExecutor(connection)
        try:
            executor.migrate([('orders', '0004_alter_returnrequest_options'),
                              ('store', '0008_watchandshop_slug_alter_productimage_is_primary')])
            executor = MigrationExecutor(connection)
            executor.migrate(old_targets)
            apps = executor.loader.project_state(old_targets).apps
            Order = apps.get_model('orders', 'Order')
            Coupon = apps.get_model('store', 'Coupon')
            order = Order.objects.create(total_amount=199, shiprocket_order_id='existing-sr',
                shiprocket_shipment_id='existing-shipment', awb_code='existing-awb')
            apps.get_model('orders', 'ShiprocketSync').objects.create(order_id=order.pk, status='Synced')
            apps.get_model('orders', 'OrderNotification').objects.create(order_id=order.pk)
            now = timezone.now()
            common = dict(valid_from=now-timedelta(days=1), valid_to=now+timedelta(days=1), usage_limit=100)
            Coupon.objects.create(code='10% OFF', discount_type='percentage', value=10, min_order_value=999, **common)
            Coupon.objects.create(code='DIWALI10', discount_type='percentage', value=10, min_order_value=199, **common)
            Coupon.objects.create(code='INFLU', discount_type='fixed', value=179, min_order_value=199, uses_count=3, **common)
            executor = MigrationExecutor(connection)
            executor.migrate(latest_targets)
            apps = executor.loader.project_state(latest_targets).apps
            upgraded = apps.get_model('orders', 'Order').objects.get(pk=order.pk)
            self.assertEqual((upgraded.shiprocket_order_id, upgraded.shiprocket_shipment_id, upgraded.awb_code),
                             ('existing-sr', 'existing-shipment', 'existing-awb'))
            self.assertEqual(upgraded.applied_discounts, [])
            self.assertEqual(apps.get_model('orders', 'ShiprocketSync').objects.get(order_id=order.pk).status, 'Synced')
            self.assertEqual(apps.get_model('orders', 'OrderNotification').objects.count(), 1)
            influ = apps.get_model('store', 'Coupon').objects.get(code='INFLU')
            self.assertEqual((influ.value, influ.uses_count, influ.min_order_value), (Decimal('179'), 3, 0))
            self.assertTrue(influ.staff_only and influ.free_shipping and not influ.auto_apply)
            from store.models import SiteConfig
            from store.promotions import quote_promotions
            config = SiteConfig.objects.create(shipping_fee=99, free_shipping_threshold=499, tax_percentage=0)
            self.assertEqual(quote_promotions(1137, 'DIWALI10', config=config)['total'], '909.60')
        finally:
            MigrationExecutor(connection).migrate(latest_targets)
