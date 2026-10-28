#!/usr/bin/env python3
"""Install the reviewed promotion release without replacing server-only settings.

Run as root on the existing VPS. All customer data and backups stay on that VPS.
The adjacent manifest pins both the uploaded server preimage and release files.
"""
import argparse
import ast
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import pwd
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
from datetime import datetime, timezone

PROJECT = Path('/var/www/rastlina/project')
PYTHON = Path('/var/www/rastlina/venv/bin/python')
SOURCE = Path(__file__).resolve().parent.parent
MANIFEST = Path(__file__).with_name('live_promotions_manifest.json')
USER = 'djangouser'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def validate_payload(source, project, entries):
    """Read and validate everything before allowing any live-file mutation."""
    payload = {}
    for entry in entries:
        name = entry['path']
        path = PurePosixPath(name)
        if path.is_absolute() or '..' in path.parts or not name.endswith('.py'):
            raise ValueError(f'Unsafe payload path: {name}')
        if path.parts[0] not in {'core', 'orders', 'store', 'payments'} or name == 'core/settings.py':
            raise ValueError(f'Protected payload path: {name}')
        target = project / name
        if target.is_symlink() or not target.parent.resolve().is_relative_to(project.resolve()):
            raise ValueError(f'Unexpected server symlink: {name}')
        data = (source / name).read_bytes()
        if digest(data) != entry['after_sha256']:
            raise ValueError(f'Release file checksum mismatch: {name}')
        ast.parse(data, filename=name)
        current = digest(target.read_bytes()) if target.exists() else None
        if current != entry['before_sha256']:
            raise ValueError(f'Server file changed since review: {name}. No installation was performed.')
        payload[name] = data
    return payload


def atomic_write(target, data, uid, gid, mode):
    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.promotion-', dir=target.parent)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
        os.chown(tmp, uid, gid)
        os.chmod(tmp, mode)
        os.replace(tmp, target)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def database_configuration():
    # Read credentials through the existing Django configuration into memory only.
    code = "import json; from django.conf import settings; print('RAS_DB_CONFIG:' + json.dumps(settings.DATABASES['default'], default=str))"
    result = subprocess.run(['runuser', '-u', USER, '--', str(PYTHON), 'manage.py', 'shell', '-c', code],
                            cwd=PROJECT, text=True, capture_output=True)
    if result.returncode:
        raise RuntimeError('Could not load the existing Django database configuration.')
    value = next((line.removeprefix('RAS_DB_CONFIG:') for line in result.stdout.splitlines()
                  if line.startswith('RAS_DB_CONFIG:')), None)
    if value is None:
        raise RuntimeError('Database configuration was unavailable; no credentials were printed.')
    config = json.loads(value)
    if config['ENGINE'] != 'django.db.backends.postgresql':
        raise RuntimeError('This installer expects the confirmed PostgreSQL deployment.')
    return config


def logged(command, log, *, cwd=PROJECT, env=None, stdout=None):
    result = subprocess.run(command, cwd=cwd, env=env, stdout=stdout or log, stderr=log)
    log.flush()
    if result.returncode:
        raise RuntimeError(f'{Path(command[0]).name} exited with status {result.returncode}; see the private deployment log.')


def django(args, log, *, cwd=PROJECT):
    logged(['runuser', '-u', USER, '--', str(PYTHON), 'manage.py', *args], log, cwd=cwd)


def preflight(payload, log, account):
    with tempfile.TemporaryDirectory(prefix='rastlina-promotions-check-') as temporary:
        stage = Path(temporary) / 'project'
        def ignore(directory, names):
            ignored = []
            for name in names:
                path = Path(directory) / name
                if path.is_symlink() or name in {'.git', 'media', 'static', 'staticfiles', '__pycache__', 'initial_watch_shop'}:
                    ignored.append(name)
                elif path.is_file() and path.suffix not in {'.py', '.html'}:
                    ignored.append(name)
            return ignored
        shutil.copytree(PROJECT, stage, ignore=ignore)
        for name, data in payload.items():
            target = stage / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        shutil.copytree(SOURCE / 'deployment', stage / 'deployment', dirs_exist_ok=True, ignore=shutil.ignore_patterns('__pycache__'))
        os.chown(temporary, account.pw_uid, account.pw_gid)
        for root, dirs, files in os.walk(stage):
            os.chown(root, account.pw_uid, account.pw_gid)
            for name in files:
                os.chown(Path(root) / name, account.pw_uid, account.pw_gid)
        isolated = '--settings=core.promotion_test_settings'
        django(['makemigrations', '--check', '--dry-run', isolated], log, cwd=stage)
        django(['test', 'store', isolated, '--noinput'], log, cwd=stage)
        logged(['runuser', '-u', USER, '--', str(PYTHON), '-m', 'unittest', 'discover', '-s', 'deployment', '-p', 'test_*.py'], log, cwd=stage)


def acceptance(log):
    code = """
from decimal import Decimal
from store.models import SiteConfig, Coupon
from store.promotions import quote_promotions
from django.contrib.auth import get_user_model
config = SiteConfig.objects.first()
assert config is not None, 'Site configuration missing'
for user in [None, get_user_model().objects.filter(is_staff=False, is_active=True).first()]:
    quote = quote_promotions('1137', 'DIWALI10', user=user, config=config)
    assert [row['discount'] for row in quote['applied_discounts']] == ['113.70', '113.70'], 'Public discount rows mismatch'
    assert quote['total'] == '909.60' and quote['shipping_fee'] == '0.00', 'Public total mismatch'
assert quote_promotions('998.99', 'DIWALI10', config=config)['coupon_discount'] == '99.90'
assert quote_promotions('999', 'DIWALI10', config=config)['coupon_discount'] == '199.80'
creator = Coupon.objects.get(code__iexact='INFLU')
assert creator.staff_only and creator.free_shipping and not creator.auto_apply and creator.min_order_value == 0
staff = get_user_model().objects.filter(is_staff=True, is_active=True).first()
assert staff is not None, 'No active staff account exists for creator orders'
creator_quote = quote_promotions('199', 'INFLU', user=staff, config=config)
assert creator_quote['shipping_fee'] == '0.00' and creator_quote['total'] == '20.00', 'Creator quote mismatch'
print('Read-only acceptance passed: public 1137 -> 909.60, creator 199 -> 20.00; no orders created.')
"""
    django(['shell', '-c', code], log)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true', help='Validate release checksums and server preimages only.')
    args = parser.parse_args()
    if not PROJECT.is_dir() or not PYTHON.is_file():
        raise SystemExit('Confirmed application paths are missing; nothing changed.')
    manifest = json.loads(MANIFEST.read_text())
    payload = validate_payload(SOURCE, PROJECT, manifest['files'])
    if args.check_only:
        print(f'CHECK PASSED: {len(payload)} reviewed files match the server; nothing changed.')
        return
    if os.geteuid() != 0:
        raise SystemExit('Run this installer as root in the existing server terminal.')
    os.umask(0o077)
    account = pwd.getpwnam(USER)
    if not shutil.which('pg_dump') or not shutil.which('pg_restore'):
        raise SystemExit('PostgreSQL backup tools are missing; nothing changed.')
    if subprocess.run(['systemctl', 'is-active', '--quiet', 'gunicorn.service']).returncode:
        raise SystemExit('Gunicorn is not active; investigate before deploying. Nothing changed.')
    socket_active = subprocess.run(['systemctl', 'is-active', '--quiet', 'gunicorn.socket']).returncode == 0
    units = ['gunicorn.socket', 'gunicorn.service'] if socket_active else ['gunicorn.service']
    stamp = datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')
    backup = Path('/var/backups/rastlina-promotions') / stamp
    backup.mkdir(parents=True, mode=0o700)
    os.chmod(backup.parent, 0o700)
    print(f'Private backup/log directory: {backup}', flush=True)
    stopped = False
    schema_started = False
    original = {}
    with (backup / 'deployment.log').open('w') as log:
        try:
            print('Checking an isolated copy against the server Python environment...', flush=True)
            preflight(payload, log, account)
            config = database_configuration()
            validate_payload(SOURCE, PROJECT, manifest['files'])
            for name in payload:
                target = PROJECT / name
                original[name] = (target.read_bytes(), target.stat()) if target.exists() else None
            with tarfile.open(backup / 'source-before.tar.gz', 'w:gz') as archive:
                for name in sorted(set(payload) | {'core/settings.py', '.env'}):
                    target = PROJECT / name
                    if target.is_file():
                        archive.add(target, arcname=name)
            (backup / 'release-manifest.json').write_text(json.dumps(manifest, indent=2))
            print('Pausing Gunicorn briefly for the database backup and migration...', flush=True)
            stopped = True
            logged(['systemctl', 'stop', *units], log)
            env = os.environ.copy()
            env['PGPASSWORD'] = str(config.get('PASSWORD') or '')
            if config.get('OPTIONS', {}).get('sslmode'):
                env['PGSSLMODE'] = str(config['OPTIONS']['sslmode'])
            command = ['runuser', '-u', USER, '--', shutil.which('pg_dump'), '--format=custom', '--no-password']
            for option, key in [('--username', 'USER'), ('--host', 'HOST'), ('--port', 'PORT')]:
                if config.get(key):
                    command.extend([option, str(config[key])])
            command.extend(['--dbname', str(config['NAME'])])
            with (backup / 'database.dump').open('wb') as output:
                logged(command, log, env=env, stdout=output)
            env.pop('PGPASSWORD', None)
            logged([shutil.which('pg_restore'), '--list', str(backup / 'database.dump')], log)
            if (backup / 'database.dump').stat().st_size == 0:
                raise RuntimeError('Database backup is empty; no release files were written.')
            for name, data in payload.items():
                previous = original[name]
                uid, gid, mode = (previous[1].st_uid, previous[1].st_gid, stat.S_IMODE(previous[1].st_mode)) if previous else (account.pw_uid, account.pw_gid, 0o644)
                atomic_write(PROJECT / name, data, uid, gid, mode)
            django(['check'], log)
            django(['migrate', '--plan'], log)
            schema_started = True
            django(['migrate', '--noinput'], log)
            django(['check'], log)
            acceptance(log)
            logged(['systemctl', 'start', *units], log)
            logged(['systemctl', 'is-active', '--quiet', 'gunicorn.service'], log)
            stopped = False
            (backup / 'SUCCESS').write_text('Promotion policy 2 installed and read-only quote checks passed.\n')
            print('SUCCESS: promotion policy 2 is active; Gunicorn is running.', flush=True)
            print('Public cart: 1137 - 113.70 - 113.70 = 909.60. INFLU: 199 - 179 + free shipping = 20.00.', flush=True)
        except Exception:
            if stopped and not schema_started:
                for name, previous in original.items():
                    if previous:
                        data, info = previous
                        atomic_write(PROJECT / name, data, info.st_uid, info.st_gid, stat.S_IMODE(info.st_mode))
                    elif (PROJECT / name).exists():
                        (PROJECT / name).unlink()
                logged(['systemctl', 'start', *units], log)
            print(f'DEPLOYMENT STOPPED. Preserve {backup}; see deployment.log for the exact failure.', file=sys.stderr)
            if stopped and schema_started:
                subprocess.run(['systemctl', 'stop', *units], stdout=log, stderr=log)
                print('Gunicorn remains paused. Do not restore the database or discard server files; request help with the log.', file=sys.stderr)
            raise


if __name__ == '__main__':
    try:
        main()
    except Exception as error:
        print(f'{type(error).__name__}: {error}', file=sys.stderr)
        sys.exit(1)
