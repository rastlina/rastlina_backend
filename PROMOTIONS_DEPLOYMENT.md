# Public and creator promotion release

This Django release is required to activate the matching frontend's new pricing.
Vercel deploys only the frontend. Merging this repository does not restart the
backend at admin.rastlina.com.

## Resulting rules

- DIWALI10 remains manually entered. It combines with the best eligible automatic
  offer. With 10% OFF at a merchandise subtotal of ₹999 or above, both discounts
  use the original subtotal: 10% + 10% = 20%, rather than a compounded 19%.
- INFLU remains manually entered and becomes staff-only. It keeps its existing
  configured discount value, expiry and usage limit, gains free delivery, and
  its minimum spend becomes zero. It does not combine with public automatic
  offers. Staff must sign in to the storefront with a staff-enabled account.
- Discount totals are capped at the merchandise subtotal. Fully covered orders
  complete with no gateway payment; stock and coupon consumption remain atomic
  and idempotent. Normal paid orders still use Razorpay verification.
- Orders retain an itemised snapshot of all applied promotions. Each code's
  usage count increments once at payment confirmation, including automatic codes.
- Admin has flags for automatic application, combining with an automatic offer,
  free shipping and staff-only access. Setting minimum order value to 0 removes
  the minimum for a shipping-waiver coupon.

## Deployment through the existing backend environment

Identify the actual service and directory first:

```
systemctl show gunicorn -p ExecStart -p WorkingDirectory --no-pager
```

If the service has a different name, identify that service; do not guess paths
or create a new database/environment. Do not print environment variables or keys.

Using the existing deployment procedure and production environment:

1. Back up the production database and confirm the existing checkout/media setup.
2. Check the checkout is clean, then fast-forward this backend repository's main
   branch. Preserve server-specific settings and environment files.
3. With the service's existing virtualenv and production settings, run
   `python manage.py migrate` and `python manage.py check`.
4. Restart the identified existing Gunicorn service and check its status.
5. Confirm `/api/store/config/` contains `promotion_policy_version: 2` and
   `/api/store/promotion-quote/` accepts quotes. The deployed frontend detects
   version 2 on the next cart open/reload and enables the new calculations.

## Read-only acceptance checks (no customer orders or payments)

- POST promotion-quote with order_total=2274 and coupon_code=DIWALI10: two
  ₹227.40 deductions, total discount ₹454.80, shipping ₹0, total ₹1819.20.
- At ₹998.99, only the entered DIWALI10 applies. At ₹999, both offers apply.
- Anonymous and non-staff customers cannot validate or quote INFLU. It must not
  appear in their active-coupons response.
- Signed-in staff: quote ₹199 with INFLU gives ₹179 off plus ₹99 shipping waived,
  leaving ₹20 payable. A subtotal below ₹179 may legitimately be fully covered.
- Quotes must reject expired, disabled, exhausted or under-minimum codes.
- Cart and checkout show the same itemised amounts. Buy again fetches current
  products/options/stock and does not copy historical coupon or exchange codes.

## Validation

Use an isolated in-memory database, with no production credentials:

```
python manage.py makemigrations --check --dry-run --settings=core.promotion_test_settings
python manage.py test store --settings=core.promotion_test_settings --noinput
```

If rolling back code/schema, use the pre-release database backup to restore
coupon configuration as well; reverse schema migration does not undo the
intentional INFLU minimum-spend data update.
