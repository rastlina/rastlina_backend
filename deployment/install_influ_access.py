#!/usr/bin/env python3
"""Upgrade an installed policy-2 server to an exact two-account INFLU allowlist.

Emails are supplied on the VPS, stored only in its database, and never embedded
in this public repository. No user accounts or staff permissions are changed.
Uses the existing guarded installer, backups, isolated tests and service recovery.
"""
import argparse
import json
from pathlib import Path
import sys

try:
    from . import install_live_promotions as installer
except ImportError:
    import install_live_promotions as installer


def normalise_emails(values):
    emails = list(dict.fromkeys(value.strip().casefold() for value in values))
    if len(emails) != 2 or any(not value or '@' not in value for value in emails):
        raise ValueError('Supply exactly two distinct account emails with --email.')
    return emails


def configure_and_acceptance(log, emails):
    code = '''
import json
from types import SimpleNamespace
from django.contrib.auth import get_user_model
from django.db import transaction
from store.models import Coupon, SiteConfig
from store.promotions import quote_promotions, eligible_coupons
emails = json.loads(EMAILS_JSON)
User = get_user_model()
permissions = list(User.objects.order_by('pk').values_list('pk', 'is_staff', 'is_superuser'))
config = SiteConfig.objects.first()
assert config is not None, 'Site configuration missing'
with transaction.atomic():
    coupon = Coupon.objects.select_for_update().get(code__iexact='INFLU')
    assert coupon.free_shipping and not coupon.auto_apply and coupon.min_order_value == 0
    before = (coupon.value, coupon.uses_count, coupon.valid_from, coupon.valid_to, coupon.usage_limit)
    coupon.allowed_emails = emails
    coupon.full_clean()
    coupon.save(update_fields=['allowed_emails'])
    coupon.refresh_from_db()
    assert set(coupon.allowed_emails) == set(emails)
    assert before == (coupon.value, coupon.uses_count, coupon.valid_from, coupon.valid_to, coupon.usage_limit)
    for email in emails:
        user = User.objects.filter(email__iexact=email, is_active=True).first()
        if user is None:
            user = SimpleNamespace(email=email, is_authenticated=True, is_active=True, is_staff=False)
        quote = quote_promotions('199', 'INFLU', user=user, config=config)
        assert quote['shipping_fee'] == '0.00' and quote['total'] == '20.00'
        assert quote['shipping_discount'] == '99.00'
        assert [row['code'] for row in quote['applied_discounts']] == ['INFLU']
        assert all('allowed_emails' not in row for row in quote['applied_discounts'])
    blocked = SimpleNamespace(email='unlisted-staff@example.invalid', is_authenticated=True, is_active=True, is_staff=True, is_superuser=True)
    for user in (None, blocked):
        try:
            quote_promotions('199', 'INFLU', user=user, config=config)
        except ValueError:
            pass
        else:
            raise AssertionError('Unlisted account was permitted')
        assert not eligible_coupons(user).filter(code__iexact='INFLU').exists()
    public = quote_promotions('1137', 'DIWALI10', config=config)
    assert public['total'] == '909.60' and public['coupon_discount'] == '227.40'
    assert list(User.objects.order_by('pk').values_list('pk', 'is_staff', 'is_superuser')) == permissions
print('Exact two-email access and free shipping verified; no users, permissions, orders or payments changed.')
'''.replace('EMAILS_JSON', repr(json.dumps(emails)))
    installer.django(['shell', '-c', code], log)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--email', action='append', required=True)
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    emails = normalise_emails(args.email)
    installer.MANIFEST = Path(__file__).with_name('influ_access_manifest.json')
    installer.acceptance = lambda log: configure_and_acceptance(log, emails)
    # The generic installer's source is this same extracted release directory.
    sys.argv = [sys.argv[0]] + (['--check-only'] if args.check_only else [])
    installer.main()
    if not args.check_only:
        print('SUCCESS: INFLU is limited to the two supplied emails, including non-staff accounts. Shipping is zero; other staff are excluded.', flush=True)


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'{type(error).__name__}: {error}', file=sys.stderr)
        sys.exit(1)
