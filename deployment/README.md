# Production-compatible promotion release

For a server where policy 2 is already installed, use the exact-email INFLU
upgrade described below. The original policy-2 installer is retained for the
previous pinned archive; do not use it to install this newer source tree.

This release merges the uploaded live server changes with promotion policy 2.
It preserves Shiprocket integration, merchant notification queues, stock locks,
bulk product editing, and the 500-character legacy video URL field. It joins the
orders and store migration branches already present on the VPS.

The installer targets `/var/www/rastlina/project` and uses the existing Python at
`/var/www/rastlina/venv/bin/python`, the `djangouser` account, and Gunicorn.

## Installation

Extract the reviewed GitHub commit archive on the existing server, then run:

```
python3 deployment/install_live_promotions.py --check-only
python3 deployment/install_live_promotions.py
```

Run from the extracted release directory as root. The first command is optional;
the second performs the same validation before proceeding.

1. Compare checksums against the supplied production source and verify the release.
2. Test a temporary candidate copy using an isolated in-memory database. These tests
   do not use the production database, payment gateway, email server or shipping API.
3. Read the existing Django database configuration locally into memory.
4. Back up affected source files, `.env` and settings under a root-only directory at
   `/var/backups/rastlina-promotions/<timestamp>`.
5. Pause Gunicorn and its socket if active, create a PostgreSQL custom-format dump,
   and verify the dump can be read before writing release files.
6. Atomically install the 20 allowlisted Python files, preserving ownership/modes.
   Existing settings, credentials, media, requirements, stock code, shipping clients,
   and other server-only files are preserved. The Git checkout/index is not reset.
7. Run Django checks and migrations. Perform read-only production quotes for public
   DIWALI10 plus 10% OFF and the staff-only INFLU shipping waiver.
8. Start Gunicorn and its socket in the prior state and verify the service is active.

The public acceptance cart is ₹1137: two ₹113.70 discounts and ₹909.60 payable.
INFLU at ₹199 keeps its ₹179 discount, waives shipping, and leaves ₹20 payable.
Both existing codes' active dates, usage limits and configured values are preserved.
Staff must use a staff-enabled storefront account for INFLU.

## Failure handling

Before migrations start, an installation failure restores any affected source
files and restarts the original service. If migrations have started, the installer
keeps Gunicorn paused and preserves all files and the database dump for inspection.
Do not apply an automatic database restore over newer customer data. Share the
failure message and the relevant deployment log with the operator before recovery.
No customer orders, payments, emails or Shiprocket requests are created by the
production acceptance quotes.

## Validation

```
python manage.py test store --settings=core.promotion_test_settings --noinput
python manage.py makemigrations --check --dry-run --settings=core.promotion_test_settings
python -m unittest discover -s deployment -p 'test_*.py'
```

30 Django tests and four installer guard tests cover public guest/customer totals,
thresholds, manual/private codes, shipping waiver, zero-total orders, duplicate
payment callbacks/webhooks, stock/coupon idempotency, shipping/notification queues,
production migration upgrade and safe installer preconditions.
# Exact-email INFLU access after policy 2 is installed

Use `install_influ_access.py --email <first-account> --email <second-account>`
from this release archive on the existing VPS. It requires the exact policy-2
file preimages, reuses the guarded installer's private database/source backups
and isolated preflight, migrates the `allowed_emails` field, then configures and
verifies those two addresses before restarting Gunicorn. Emails stay in the
server database, outside public source. No accounts are created or promoted.
The explicit list takes priority over staff status; other staff cannot use INFLU.
Empty or invalid INFLU lists deny everyone. Login is required and access uses the
authenticated account email, never the delivery email in a checkout form.
The existing discount value, expiry, usage limits and free-shipping rule remain.
