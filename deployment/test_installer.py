import hashlib
import os
from pathlib import Path
import tempfile
import unittest
from deployment.install_live_promotions import validate_payload, atomic_write


class InstallerGuardTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.live = self.root / 'source', self.root / 'live'
        for path in (self.source, self.live):
            (path / 'store').mkdir(parents=True)
        self.before, self.after = b'old = 1\r\n', b'new = 2\n'
        (self.live / 'store/models.py').write_bytes(self.before)
        (self.source / 'store/models.py').write_bytes(self.after)
        self.entries = [{'path': 'store/models.py', 'before_sha256': self.sha(self.before), 'after_sha256': self.sha(self.after)}]

    @staticmethod
    def sha(data):
        return hashlib.sha256(data).hexdigest()

    def test_exact_supplied_server_preimage_is_required_and_validation_does_not_write(self):
        self.assertEqual(validate_payload(self.source, self.live, self.entries)['store/models.py'], self.after)
        self.assertEqual((self.live / 'store/models.py').read_bytes(), self.before)
        (self.live / 'store/models.py').write_text('another developer edit\n')
        with self.assertRaisesRegex(ValueError, 'changed since review'):
            validate_payload(self.source, self.live, self.entries)

    def test_new_files_cannot_overwrite_existing_files_and_tampered_payloads_are_rejected(self):
        self.entries[0]['before_sha256'] = None
        with self.assertRaisesRegex(ValueError, 'changed since review'):
            validate_payload(self.source, self.live, self.entries)
        self.entries[0]['before_sha256'] = self.sha(self.before)
        (self.source / 'store/models.py').write_text('tampered = 3\n')
        with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
            validate_payload(self.source, self.live, self.entries)

    def test_settings_traversal_and_server_symlinks_are_protected(self):
        for name in ('core/settings.py', '../escape.py', '/tmp/escape.py'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_payload(self.source, self.live, [{**self.entries[0], 'path': name}])
        (self.live / 'store/models.py').unlink()
        (self.live / 'store/models.py').symlink_to(self.source / 'store/models.py')
        with self.assertRaisesRegex(ValueError, 'symlink'):
            validate_payload(self.source, self.live, self.entries)

    def test_atomic_replacement_preserves_requested_owner_and_permissions(self):
        target = self.live / 'store/models.py'
        atomic_write(target, self.after, os.getuid(), os.getgid(), 0o640)
        self.assertEqual(target.read_bytes(), self.after)
        self.assertEqual(target.stat().st_mode & 0o777, 0o640)
        self.assertEqual(list(target.parent.glob('.promotion-*')), [])
