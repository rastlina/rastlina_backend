from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
from django.db import transaction
from django.test import TestCase
from django.utils import timezone
from rest_framework.test import APIClient
from accounts.models import CustomUser
from orders.models import Order
from payments.services import _consume_coupon_and_exchange, complete_zero_total_order
from store.models import Coupon, SiteConfig, MainCategory, Category, Product, ProductVariant, SizeOption
from store.promotions import quote_promotions


class PromotionTests(TestCase):
    def setUp(self):
        self.client = APIClient()
        self.staff = CustomUser.objects.create_user('owner@example.invalid', is_staff=True)
        self.customer = CustomUser.objects.create_user('customer@example.invalid')
        self.config = SiteConfig.objects.create(shipping_fee=99, free_shipping_threshold=499, tax_percentage=0)
        now = timezone.now()
        common = dict(valid_from=now-timedelta(days=1), valid_to=now+timedelta(days=1), usage_limit=100)
        self.auto = Coupon.objects.create(code='10% OFF', discount_type='percentage', value=10,
                                         min_order_value=999, auto_apply=True, **common)
        self.diwali = Coupon.objects.create(code='DIWALI10', discount_type='percentage', value=10,
                                            min_order_value=199, combine_with_automatic=True, **common)
        self.influ = Coupon.objects.create(code='INFLU', discount_type='fixed', value=179,
                                          min_order_value=0, staff_only=True, free_shipping=True, **common)
        main = MainCategory.objects.create(name='Plants')
        cat = Category.objects.create(name='Indoor', main_category=main)
        self.product = Product.objects.create(name='Plant', sku='TEST', category=cat, price=379)
        self.size = SizeOption.objects.create(name='Small')
        self.variant = ProductVariant.objects.create(product=self.product, size=self.size, stock=20)

    def quote(self, subtotal, code='', user=None):
        return quote_promotions(subtotal, code, user=user, config=self.config)

    def test_twenty_percent_is_additive_not_compounded(self):
        result = self.quote(2274, 'DIWALI10')
        self.assertEqual([row['code'] for row in result['applied_discounts']], ['DIWALI10', '10% OFF'])
        self.assertEqual([row['discount'] for row in result['applied_discounts']], ['227.40', '227.40'])
        self.assertEqual(result['coupon_discount'], '454.80')
        self.assertEqual(result['total'], '1819.20')

    def test_exact_threshold_and_below(self):
        self.assertEqual(self.quote(999, 'DIWALI10')['coupon_discount'], '199.80')
        self.assertEqual(self.quote('998.99', 'DIWALI10')['coupon_discount'], '99.90')

    def test_manual_diwali_is_not_applied_automatically(self):
        self.assertEqual(self.quote(379)['applied_discounts'], [])
        self.assertEqual(self.quote(2274)['coupon_discount'], '227.40')

    def test_same_automatic_coupon_is_not_duplicated(self):
        self.assertEqual(len(self.quote(2274, '10% OFF')['applied_discounts']), 1)

    def test_private_influ_has_no_minimum_and_waives_shipping(self):
        result = self.quote(199, 'INFLU', self.staff)
        self.assertEqual(result['coupon_discount'], '179.00')
        self.assertEqual(result['shipping_fee'], '0.00')
        self.assertEqual(result['shipping_discount'], '99.00')
        self.assertEqual(result['total'], '20.00')

    def test_creator_order_below_old_minimum_is_allowed_and_capped(self):
        result = self.quote(100, 'INFLU', self.staff)
        self.assertEqual(result['total'], '0.00')
        self.assertEqual(result['coupon_discount'], '100.00')

    def test_private_creator_discount_is_exclusive_of_public_automatic(self):
        result = self.quote(2274, 'INFLU', self.staff)
        self.assertEqual([row['code'] for row in result['applied_discounts']], ['INFLU'])

    def test_guest_and_regular_customers_cannot_use_influ(self):
        for user in (None, self.customer):
            with self.subTest(user=user), self.assertRaisesRegex(ValueError, 'authorised staff'):
                self.quote(199, 'INFLU', user)

    def test_private_codes_never_appear_in_public_lists(self):
        response = self.client.get('/api/store/active-coupons/')
        self.assertEqual(response.status_code, 200)
        self.assertNotIn('INFLU', [row['code'] for row in response.data])
        self.client.force_authenticate(self.staff)
        response = self.client.get('/api/store/active-coupons/')
        self.assertIn('INFLU', [row['code'] for row in response.data])

    def test_api_quote_enforces_staff_permission_and_returns_both_public_rows(self):
        response = self.client.post('/api/store/promotion-quote/', {'order_total': 2274, 'coupon_code': 'DIWALI10'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['total'], '1819.20')
        response = self.client.post('/api/store/promotion-quote/', {'order_total': 199, 'coupon_code': 'INFLU'})
        self.assertEqual(response.status_code, 400)

    def test_expiry_inactive_and_usage_limits_remove_automatic_offer(self):
        for change in ({'active': False}, {'uses_count': 100}, {'valid_to': timezone.now()-timedelta(seconds=1)}):
            with self.subTest(change=change):
                Coupon.objects.filter(pk=self.auto.pk).update(**change)
                self.assertEqual(len(self.quote(2274, 'DIWALI10')['applied_discounts']), 1)
                self.auto.save()

    def test_manual_minimum_and_expiry_are_enforced(self):
        with self.assertRaisesRegex(ValueError, 'Minimum order'):
            self.quote(198, 'DIWALI10')
        self.diwali.active = False
        self.diwali.save()
        with self.assertRaisesRegex(ValueError, 'expired'):
            self.quote(379, 'DIWALI10')

    def test_invalid_money_is_rejected(self):
        for value in ('NaN', 'Infinity', '-1', 'no', None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.quote(value)

    def payload(self, code='DIWALI10', policy=2):
        return {'items': [{'variant_id': self.variant.pk, 'quantity': 6, 'price': '0.01'}],
                'coupon_code': code, 'promotion_policy_version': policy, 'address': 'Test street',
                'city': 'Test city', 'state': 'Test state', 'zip_code': '500001', 'email': 'test@example.invalid'}

    @patch('payments.razorpay_client.create_order', return_value={'id': 'order_test', 'amount': 181920, 'currency': 'INR'})
    def test_checkout_recomputes_prices_and_uses_same_twenty_percent_quote(self, gateway):
        response = self.client.post('/api/orders/checkout/', self.payload(), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        order = Order.objects.get(pk=response.data['order_id'])
        self.assertEqual(order.subtotal, Decimal('2274.00'))
        self.assertEqual(order.discount_amount, Decimal('454.80'))
        self.assertEqual(order.total_amount, Decimal('1819.20'))
        gateway.assert_called_once_with(Decimal('1819.20'))
        self.assertEqual(len(order.applied_discounts), 2)
        self.assertEqual(self.auto.uses_count, 0)  # checkout is read-only for usage

    @patch('payments.razorpay_client.create_order', return_value={'id': 'order_legacy', 'amount': 204660})
    def test_legacy_clients_keep_their_single_coupon_amount_until_refresh(self, gateway):
        response = self.client.post('/api/orders/checkout/', self.payload(policy=1), format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertEqual(Order.objects.get(pk=response.data['order_id']).discount_amount, Decimal('227.40'))

    @patch('payments.razorpay_client.create_order', return_value={'id': 'creator', 'amount': 2000})
    def test_checkout_waives_creator_shipping(self, gateway):
        self.product.price = 199
        self.product.save()
        self.client.force_authenticate(self.staff)
        payload = self.payload('INFLU')
        payload['items'][0]['quantity'] = 1
        response = self.client.post('/api/orders/checkout/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        order = Order.objects.get(pk=response.data['order_id'])
        self.assertEqual(order.shipping_fee, 0)
        gateway.assert_called_once_with(Decimal('20.00'))

    @patch('payments.razorpay_client.create_order')
    def test_zero_total_creator_order_completes_without_gateway_and_only_once(self, gateway):
        self.product.price = 100
        self.product.save()
        self.client.force_authenticate(self.staff)
        payload = self.payload('INFLU')
        payload['items'][0]['quantity'] = 1
        response = self.client.post('/api/orders/checkout/', payload, format='json')
        self.assertEqual(response.status_code, 201, response.data)
        self.assertFalse(response.data['payment_required'])
        gateway.assert_not_called()
        complete_zero_total_order(response.data['order_id'])
        self.variant.refresh_from_db()
        self.influ.refresh_from_db()
        order = Order.objects.get(pk=response.data['order_id'])
        self.assertEqual(order.payment_status, 'Paid')
        self.assertEqual(order.order_status, 'Processing')
        self.assertEqual(self.variant.stock, 19)
        self.assertEqual(self.influ.uses_count, 1)

    def test_every_applied_coupon_consumed_once(self):
        order = Order.objects.create(total_amount=1819.2, coupon_code='DIWALI10',
                                    applied_discounts=self.quote(2274, 'DIWALI10')['applied_discounts'])
        with transaction.atomic():
            _consume_coupon_and_exchange(order)
            _consume_coupon_and_exchange(order)
        self.auto.refresh_from_db()
        self.diwali.refresh_from_db()
        self.assertEqual(self.auto.uses_count, 1)
        self.assertEqual(self.diwali.uses_count, 1)

    def test_historical_orders_still_consume_single_coupon(self):
        order = Order.objects.create(total_amount=100, coupon_code='DIWALI10')
        with transaction.atomic():
            _consume_coupon_and_exchange(order)
        self.diwali.refresh_from_db()
        self.assertEqual(self.diwali.uses_count, 1)

    @patch('payments.services.verify_payment_signature', return_value=True)
    def test_payment_capture_consumes_both_public_codes_only_once(self, signature):
        from payments.services import capture_payment_from_client
        from orders.models import OrderItem
        order = Order.objects.create(total_amount=1819.2, coupon_code='DIWALI10', razorpay_order_id='order_capture',
                                    applied_discounts=self.quote(2274, 'DIWALI10')['applied_discounts'])
        OrderItem.objects.create(order=order, product=self.product, variant=self.variant, product_name='Plant', price=379, quantity=6)
        self.assertTrue(capture_payment_from_client('order_capture', 'payment_test', 'signature')['success'])
        self.assertTrue(capture_payment_from_client('order_capture', 'payment_test', 'signature')['success'])
        self.auto.refresh_from_db(); self.diwali.refresh_from_db(); self.variant.refresh_from_db()
        self.assertEqual(self.auto.uses_count, 1)
        self.assertEqual(self.diwali.uses_count, 1)
        self.assertEqual(self.variant.stock, 14)

    def test_data_migration_configures_existing_codes_without_altering_value(self):
        import importlib
        from django.apps import apps
        self.influ.min_order_value = 199
        self.influ.staff_only = False
        self.influ.free_shipping = False
        self.influ.uses_count = 2
        self.influ.save()
        importlib.import_module('store.migrations.0010_coupon_promotion_policy').configure_existing_codes(apps, None)
        self.influ.refresh_from_db()
        self.assertEqual(self.influ.value, Decimal('179'))
        self.assertEqual(self.influ.uses_count, 2)
        self.assertEqual(self.influ.min_order_value, 0)
        self.assertTrue(self.influ.staff_only)
        self.assertTrue(self.influ.free_shipping)
