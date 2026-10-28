import re
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from .models import Order
from .shipping_models import ShiprocketSync
from .shiprocket_client import _call


def parcel_for(order):
    count = 0
    for item in order.items.select_related('product__category'):
        product = item.product
        name = item.product_name
        category = str(product.category) if product and product.category else ''
        match = re.search(r'(?:set\s*(?:of\s*)?|combos?\s*(?:of\s*)?)([2-9]\d*)',
                          category + ' ' + name, re.I)
        per_unit = int(match.group(1)) if match else 1
        if 'combo' in category.lower() and not match:
            if '|' in name:
                per_unit = len(name.split('|'))
            else:
                raise ValueError('Could not identify the number of plants in this combo.')
        count += item.quantity * per_unit
    if count < 1:
        raise ValueError('Order has no items.')
    return count, {'length': 12 * count, 'breadth': 12, 'height': 32,
                   'weight': float(Decimal('0.420') * count)}


def find_remote_order(order):
    source_id = f'RST-{order.pk}'
    for search in [source_id, str(order.pk)]:
        page = 1
        while True:
            data = _call('GET', '/orders', params={'search': search, 'per_page': 100, 'page': page})
            for row in data.get('data', []):
                exact = str(row.get('channel_order_id', '')) == source_id
                legacy = (str(row.get('channel_order_id', '')) == str(order.pk)
                          and str(row.get('comment', '')).strip() == f'Rastlina order #{order.pk}')
                if exact or legacy:
                    return row
            pages = data.get('meta', {}).get('pagination', {}).get('total_pages', 1)
            if page >= int(pages or 1):
                break
            page += 1
    return None


def remote_ids(row):
    sr_id = row.get('order_id') or row.get('id')
    shipment_id = row.get('shipment_id')
    shipments = row.get('shipments') or []
    if not shipment_id and shipments:
        shipment_id = shipments[0].get('id')
    if not sr_id:
        raise ValueError('Shiprocket did not return its order ID.')
    return str(sr_id), str(shipment_id) if shipment_id else ''


def sync_paid_order(order_id):
    from .shiprocket_client import create_shiprocket_order
    with transaction.atomic():
        order = Order.objects.select_for_update().get(pk=order_id)
        if order.payment_status != 'Paid' or order.order_status in ['Cancelled', 'Shipped', 'Delivered']:
            raise ValueError('Only paid, unshipped, non-cancelled orders can sync.')
        if order.shiprocket_order_id:
            return {'order_id': order.shiprocket_order_id, 'shipment_id': order.shiprocket_shipment_id}
        remote = find_remote_order(order)
        if remote is None:
            count, package = parcel_for(order)
            ShiprocketSync.objects.filter(order_id=order_id).update(plant_count=count)
            remote = create_shiprocket_order(order, package=package)
        sr_id, shipment_id = remote_ids(remote)
        order.shiprocket_order_id = sr_id
        order.shiprocket_shipment_id = shipment_id
        order.save(update_fields=['shiprocket_order_id', 'shiprocket_shipment_id'])
        return {'order_id': sr_id, 'shipment_id': shipment_id}


def queue_sync(order):
    if order.payment_status != 'Paid' or order.order_status in ['Cancelled', 'Shipped', 'Delivered']:
        return {'success': False, 'error': 'Only paid, unshipped orders can be synced.'}
    row, _ = ShiprocketSync.objects.get_or_create(order_id=order.pk)
    if row.status != 'Synced':
        row.status = 'Pending'
        row.next_attempt_at = timezone.now()
        row.last_error = ''
        row.save(update_fields=['status', 'next_attempt_at', 'last_error'])
    return {'success': True, 'queued': row.status != 'Synced'}

