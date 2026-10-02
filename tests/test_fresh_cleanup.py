"""Transaction identity, no-follow cleanup and partial account failure regressions."""
import json
import os
from pathlib import Path
import subprocess
import stat
import tempfile
import unittest
from unittest import mock

from test_safety import ROOT, s


class FreshCleanupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.roots = [str(self.base / name) for name in ('config', 'data', 'state')]
        self.ledger = str(self.base / 'fresh-ownership.json')
        s.fresh_init(self.ledger, *self.roots)
        self.tools = self.base / 'tools'
        self.tools.mkdir()
        for tool in ('getent', 'useradd', 'userdel', 'groupdel'):
            (self.tools / tool).symlink_to(ROOT / 'tests/account_fixture.py')
        self.accounts = self.base / 'accounts'
        self.env = mock.patch.dict(os.environ, {
            'PATH': str(self.tools) + ':' + os.environ['PATH'],
            'FIXTURE_ACCOUNTS': str(self.accounts),
        })
        self.env.start()
        self.addCleanup(self.env.stop)

    def create_dirs(self):
        for directory in self.roots:
            s.fresh_mkdir(self.ledger, directory, '0750')
        for name in ('state', 'public'):
            s.fresh_mkdir(self.ledger, str(Path(self.roots[1]) / name), '0750')

    def test_runtime_files_and_symlinks_removed_without_following_targets(self):
        self.create_dirs()
        outside = self.base / 'unrelated'
        outside.mkdir()
        (outside / 'keep').write_text('unrelated root state')
        runtime = Path(self.roots[1]) / 'state'
        (runtime / 'nested').mkdir()
        (runtime / 'nested/cache').write_text('runtime cache')
        (runtime / 'escape').symlink_to(outside, target_is_directory=True)
        s.fresh_cleanup_dirs(self.ledger, *self.roots)
        self.assertTrue(all(not os.path.lexists(root) for root in self.roots))
        self.assertEqual((outside / 'keep').read_text(), 'unrelated root state')

    def test_directory_modes_ignore_restrictive_manager_umask(self):
        original = os.umask(0o077)
        try:
            s.fresh_mkdir(self.ledger, self.roots[0], '0750')
            s.fresh_mkdir(self.ledger, self.roots[2], '0700')
        finally:
            os.umask(original)
        self.assertEqual(stat.S_IMODE(Path(self.roots[0]).stat().st_mode), 0o750)
        self.assertEqual(stat.S_IMODE(Path(self.roots[2]).stat().st_mode), 0o700)

    def test_preexisting_directory_never_adopted(self):
        Path(self.roots[0]).mkdir()
        marker = Path(self.roots[0]) / 'keep'
        marker.write_text('preexisting')
        with self.assertRaises(FileExistsError): s.fresh_mkdir(self.ledger, self.roots[0], '0750')
        self.assertEqual(json.loads(Path(self.ledger).read_text())['directories'], [])
        with self.assertRaises(ValueError): s.fresh_init(str(self.base / 'other-ledger'), *self.roots)
        self.assertEqual(marker.read_text(), 'preexisting')

    def test_replaced_directory_symlink_and_wrong_roots_fail_before_deletion(self):
        self.create_dirs()
        original = Path(self.roots[1])
        original.rename(self.base / 'saved')
        original.symlink_to(self.base / 'saved', target_is_directory=True)
        with self.assertRaises(ValueError): s.fresh_cleanup_dirs(self.ledger, *self.roots)
        self.assertTrue(Path(self.roots[0]).exists())
        original.unlink()
        original.mkdir()
        (original / 'unrelated').write_text('keep')
        with self.assertRaises(ValueError): s.fresh_cleanup_dirs(self.ledger, *self.roots)
        self.assertTrue((original / 'unrelated').exists())
        with self.assertRaises(ValueError): s.fresh_cleanup_dirs(self.ledger, self.roots[0], str(self.base), self.roots[2])

    def test_same_device_bind_mount_refused(self):
        self.create_dirs()
        mounted = Path(self.roots[1]) / 'state'
        original = Path.read_text
        def read(path, *args, **kwargs):
            if str(path) == '/proc/self/mountinfo':
                return '1 0 0:0 / ' + str(mounted) + ' rw - tmpfs tmpfs rw\n'
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, 'read_text', read), self.assertRaises(ValueError):
            s.fresh_cleanup_dirs(self.ledger, *self.roots)
        self.assertTrue(all(Path(root).exists() for root in self.roots))

    def test_cleanup_failure_preserves_account_and_ownership_evidence(self):
        s.fresh_account_create(self.ledger, self.roots[1])
        self.create_dirs()
        (Path(self.roots[2]) / 'state-file').write_text('created')
        with mock.patch.object(s.os, 'unlink', side_effect=PermissionError('fixture')), self.assertRaises(PermissionError):
            s.fresh_cleanup_dirs(self.ledger, *self.roots)
        self.assertTrue((self.accounts / 'passwd').exists())
        self.assertIsNotNone(json.loads(Path(self.ledger).read_text())['account'])
        with self.assertRaises(ValueError): s.fresh_cleanup_account(self.ledger, *self.roots)

    def test_created_account_cleanup_and_userdel_already_removed_group(self):
        for automatic in ('0', '1'):
            with self.subTest(automatic=automatic):
                if automatic == '1':
                    Path(self.ledger).unlink()
                    s.fresh_init(self.ledger, *self.roots)
                s.fresh_account_create(self.ledger, self.roots[1])
                self.create_dirs()
                s.fresh_cleanup_dirs(self.ledger, *self.roots)
                with mock.patch.dict(os.environ, {'FIXTURE_USERDEL_REMOVES_GROUP': automatic}):
                    s.fresh_cleanup_account(self.ledger, *self.roots)
                self.assertFalse((self.accounts / 'passwd').exists())
                self.assertFalse((self.accounts / 'group').exists())

    def test_identity_change_refuses_cleanup_and_account_deletion(self):
        s.fresh_account_create(self.ledger, self.roots[1])
        self.create_dirs()
        passwd = self.accounts / 'passwd'
        passwd.write_text(passwd.read_text().replace('424242', '424243', 1))
        with self.assertRaises(ValueError): s.fresh_cleanup_dirs(self.ledger, *self.roots)
        with self.assertRaises(ValueError): s.fresh_cleanup_account(self.ledger, *self.roots)
        self.assertTrue(all(Path(root).exists() for root in self.roots))
        self.assertNotIn('userdel ', (self.accounts / 'commands').read_text())

    def test_userdel_and_groupdel_failures_remain_recoverable(self):
        s.fresh_account_create(self.ledger, self.roots[1])
        self.create_dirs()
        s.fresh_cleanup_dirs(self.ledger, *self.roots)
        for tool in ('USERDEL', 'GROUPDEL'):
            with mock.patch.dict(os.environ, {'FIXTURE_' + tool + '_FAIL': '1'}), self.assertRaises(subprocess.CalledProcessError):
                s.fresh_cleanup_account(self.ledger, *self.roots)
            self.assertIsNotNone(json.loads(Path(self.ledger).read_text())['account'])
        # An unrelated new telemt identity after userdel must not lose its group.
        (self.accounts / 'passwd').write_text('telemt:x:424243:424242::/unrelated:/bin/sh\n')
        with self.assertRaises(ValueError): s.fresh_cleanup_account(self.ledger, *self.roots)
        self.assertTrue((self.accounts / 'group').exists())
        (self.accounts / 'passwd').unlink()
        s.fresh_cleanup_account(self.ledger, *self.roots)
        self.assertFalse((self.accounts / 'group').exists())

    def test_partial_useradd_is_not_guessed_as_owned(self):
        with mock.patch.dict(os.environ, {'FIXTURE_PARTIAL_USERADD': '1'}), self.assertRaises(subprocess.CalledProcessError):
            s.fresh_account_create(self.ledger, self.roots[1])
        with self.assertRaises(ValueError): s.fresh_cleanup_dirs(self.ledger, *self.roots)
        self.assertTrue((self.accounts / 'group').exists())
        self.assertTrue(json.loads(Path(self.ledger).read_text())['pending_account'])
        self.assertNotIn('groupdel ', (self.accounts / 'commands').read_text())

    def test_preexisting_account_never_deleted(self):
        self.accounts.mkdir()
        (self.accounts / 'passwd').write_text('telemt:x:424242:424242::/unrelated:/bin/sh\n')
        with self.assertRaises(ValueError): s.fresh_account_create(self.ledger, self.roots[1])
        s.fresh_cleanup_account(self.ledger, *self.roots)
        self.assertTrue((self.accounts / 'passwd').exists())
        self.assertNotIn('userdel ', (self.accounts / 'commands').read_text())

    def test_active_uid_or_shared_gid_refuses_before_deletion(self):
        s.fresh_account_create(self.ledger, self.roots[1])
        self.create_dirs()
        original = Path.read_text
        def read(path, *args, **kwargs):
            if str(path) == '/proc/123/status':
                return 'Uid:\t424242\t424242\t424242\t424242\n'
            return original(path, *args, **kwargs)
        with mock.patch.object(Path, 'iterdir', return_value=[Path('/proc/123')]), \
                mock.patch.object(Path, 'read_text', read), self.assertRaises(ValueError):
            s.fresh_cleanup_dirs(self.ledger, *self.roots)
        account = json.loads(Path(self.ledger).read_text())['account']['user']
        with mock.patch.object(s, 'fresh_passwd', return_value=[account, ['other', 'x', '7', '424242', '', '/', '/bin/sh']]), \
                self.assertRaises(ValueError):
            s.fresh_cleanup_dirs(self.ledger, *self.roots)
        self.assertTrue(all(Path(root).exists() for root in self.roots))

    def test_interrupted_directory_cleanup_resumes_from_owned_identity(self):
        s.fresh_account_create(self.ledger, self.roots[1])
        self.create_dirs()
        (Path(self.roots[1]) / 'state/runtime').write_text('cache')
        original = s.os.unlink
        def unlink(name, *args, **kwargs):
            if name == 'runtime': raise PermissionError('fixture interrupted rollback')
            return original(name, *args, **kwargs)
        with mock.patch.object(s.os, 'unlink', unlink), self.assertRaises(PermissionError):
            s.fresh_cleanup_dirs(self.ledger, *self.roots)
        self.assertFalse(Path(self.roots[2]).exists())
        self.assertTrue(Path(self.roots[1]).exists())
        s.fresh_cleanup_dirs(self.ledger, *self.roots)
        s.fresh_cleanup_account(self.ledger, *self.roots)
        self.assertFalse((self.accounts / 'passwd').exists())
