#!/usr/bin/env python3
"""Bounded repository identity and public CLI migration fixtures; no network."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
PRIMARY = 'xPROMSx/telegram-web-proxy-manager'
LEGACY = 'xPROMSx/telemt-web-manager'


def repository(name):
    return dict(id=1398514078, full_name=name, name=name.split('/')[1],
                html_url='https://github.com/' + name,
                owner=dict(id=102687702, login='xPROMSx'),
                private=False, fork=False, archived=False, disabled=False)


class RepositoryTransition(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='manager-rename-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        for key, name in (('primary', PRIMARY), ('legacy', LEGACY)):
            (self.root / (key + '.json')).write_text(json.dumps(repository(name)))
            (self.root / (key + '.status')).write_text('200')
            (self.root / (key + '-release.json')).write_text(json.dumps(dict(
                draft=False, prerelease=False, tag_name='v1.1.0',
                published_at='2026-10-07T00:00:00Z',
                html_url='https://github.com/' + name + '/releases/tag/v1.1.0')))

    def resolve(self, success=True):
        script = r'''source "$1"; BOOTSTRAP_TMP=$2
bootstrap_repository_metadata() {
    local key=legacy
    [[ $1 != "$PRIMARY_MANAGER_REPO" ]] || key=primary
    printf '%s\n' "$1" >>"$BOOTSTRAP_TMP/requests"
    cp "$BOOTSTRAP_TMP/$key.json" "$2"
    cat "$BOOTSTRAP_TMP/$key.status"
}
bootstrap_download() {
    printf '%s\n' "$1" >>"$BOOTSTRAP_TMP/requests"
    case $1 in
        */releases/tags/v1.1.0)
            local key=legacy
            [[ $MANAGER_REPO != "$PRIMARY_MANAGER_REPO" ]] || key=primary
            cp "$BOOTSTRAP_TMP/$key-release.json" "$2";;
        */git/ref/tags/v1.1.0)
            printf '{"ref":"refs/tags/v1.1.0","object":{"type":"tag","sha":"%040d"}}' 2 >"$2";;
        */git/tags/*)
            printf '{"sha":"%040d","object":{"type":"commit","sha":"%040d"}}' 2 1 >"$2";;
        *) return 1;;
    esac
}
VERSION=v1.1.0; resolve_manager_repository; resolve_manager_release
printf '%s %s %s\n' "$MANAGER_REPO" "$MANAGER_TAG" "$MANAGER_COMMIT"
'''
        result = subprocess.run(['bash', '-c', script, 'fixture', str(ROOT / 'install.sh'),
                                 str(self.root)], capture_output=True, timeout=10)
        self.assertEqual(result.returncode == 0, success, result.stderr.decode())
        return result.stdout.decode(), (self.root / 'requests').read_text().splitlines()

    def test_pre_rename_404_falls_back_to_valid_legacy(self):
        (self.root / 'primary.status').write_text('404')
        output, calls = self.resolve()
        self.assertEqual(calls[:2], [PRIMARY, LEGACY])
        self.assertTrue(output.startswith(LEGACY + ' v1.1.0 '))
        self.assertTrue(all(LEGACY in url for url in calls[2:]))

    def test_post_rename_uses_primary_without_legacy_redirect(self):
        output, calls = self.resolve()
        self.assertTrue(output.startswith(PRIMARY + ' v1.1.0 '))
        self.assertTrue(all(PRIMARY in url for url in calls))

    def test_network_failure_and_non_404_never_fall_back(self):
        for status in ('000', '403', '429', '500'):
            with self.subTest(status=status):
                (self.root / 'requests').unlink(missing_ok=True)
                (self.root / 'primary.status').write_text(status)
                _, calls = self.resolve(False)
                self.assertEqual(calls, [PRIMARY])

    def test_foreign_wrong_canonical_or_identity_metadata_refused(self):
        original = repository(PRIMARY)
        for changes in (dict(full_name='attacker/foreign'), dict(full_name=LEGACY),
                        dict(id=1), dict(owner=dict(id=1, login='xPROMSx')),
                        dict(html_url='https://github.com/attacker/foreign'),
                        dict(private=True), dict(fork=True), dict(archived=True),
                        dict(disabled=True), dict(name='other')):
            with self.subTest(changes=changes):
                (self.root / 'requests').unlink(missing_ok=True)
                (self.root / 'primary.json').write_text(json.dumps(original | changes))
                _, calls = self.resolve(False)
                self.assertEqual(calls, [PRIMARY])

    def test_malformed_and_duplicate_metadata_refused(self):
        for value in ('{', '[]', '{}', '{"id":1,"id":1398514078}'):
            with self.subTest(value=value):
                (self.root / 'requests').unlink(missing_ok=True)
                (self.root / 'primary.json').write_text(value)
                _, calls = self.resolve(False)
                self.assertEqual(calls, [PRIMARY])

    def test_foreign_release_url_refused_for_each_selected_identity(self):
        for key in ('primary', 'legacy'):
            with self.subTest(key=key):
                (self.root / 'primary.status').write_text('200' if key == 'primary' else '404')
                value = json.loads((self.root / (key + '-release.json')).read_text())
                value['html_url'] = 'https://github.com/attacker/foreign/releases/tag/v1.1.0'
                (self.root / (key + '-release.json')).write_text(json.dumps(value))
                _, calls = self.resolve(False)
                self.assertFalse(any('/git/' in url for url in calls))


@unittest.skipUnless(os.geteuid() == 0, 'real root-owned bootstrap fixture')
class LauncherMigration(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='manager-launchers-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.source = self.root / 'source'; self.source.mkdir(0o700)
        (self.root / 'opt').mkdir(0o700); (self.root / 'bin').mkdir(0o700)
        (self.root / 'lock').mkdir(0o700)
        self.dest = self.root / 'opt/telemt-web-manager'
        self.legacy = self.root / 'bin/telemt-web-manager'
        self.canonical = self.root / 'bin/telegram-web-proxy-manager'
        for src, target in ((ROOT / 'telemt-web-manager.sh', self.source / 'telemt-web-manager.sh'),
                            (ROOT / 'lib/safety.py', self.source / 'safety.py')):
            target.write_bytes(src.read_bytes()); target.chmod(0o600)

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mode,
                                               p.stat().st_uid, p.stat().st_gid)
                for directory in (self.root / 'opt', self.root / 'bin')
                for p in directory.rglob('*') if p.is_file()}

    def install(self, success=True, injection='', tag='v1.1.2'):
        # No production bypass: inject errors into this fixture's Python interpreter.
        code = '''source "$1"; BOOTSTRAP_TMP=$2/source; INSTALL_DIR=$2/opt/telemt-web-manager
LAUNCHER=$2/bin/telemt-web-manager; BOOTSTRAP_LOCK=$2/lock/manager.lock
MANAGER_STATE=$2/state; MANAGER_SYSTEMD_ROOT=$2/systemd; MANAGER_TAG=v1.1.2
'''
        if injection:
            (self.root / 'inject.py').write_text(injection)
            code += '''python3() { { cat "$BOOTSTRAP_TMP/../inject.py"; cat; } | command python3 "$@"; }
'''
        code += 'MANAGER_TAG=$3; validate_manager_pair; commit_manager_pair'
        result = subprocess.run(['bash', '-c', code, 'fixture', str(ROOT / 'install.sh'),
                                 str(self.root), tag], capture_output=True, timeout=10)
        self.assertEqual(result.returncode == 0, success, result.stderr.decode())
        self.assertFalse(list((self.root / 'bin').glob('.telemt-web-manager.*')))
        self.assertFalse(list((self.root / 'opt').glob('.telemt-web-manager.*')))
        return result

    def assert_launchers(self):
        for path in (self.legacy, self.canonical):
            info = path.lstat()
            self.assertFalse(path.is_symlink())
            self.assertEqual((info.st_uid, info.st_gid, info.st_mode & 0o7777, info.st_nlink),
                             (0, 0, 0o755, 1))
            result = subprocess.run([str(path), '--help'], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0)
            self.assertIn(b'Telegram Web Proxy Manager 1.1.2', result.stdout)
            self.assertIn(b'Usage: telegram-web-proxy-manager', result.stdout)
        self.assertEqual(self.legacy.read_bytes(), self.canonical.read_bytes())

    def test_clean_install_and_rerun_both_commands(self):
        self.install(); self.assert_launchers()
        before = self.snapshot(); self.install(); self.assertEqual(before, self.snapshot())

    def test_pre_rename_published_101_candidate_is_still_accepted(self):
        path = self.source / 'telemt-web-manager.sh'
        path.write_text(path.read_text().replace('# Telegram Web Proxy Manager.',
            '# Telemt WEB Manager.').replace('SCRIPT_VERSION=1.1.2', 'SCRIPT_VERSION=1.0.1'))
        helper = self.source / 'safety.py'
        helper.write_text(helper.read_text().replace("UPDATE_MANAGER_VERSION = '1.1.2'", "UPDATE_MANAGER_VERSION = '1.0.1'"))
        self.install(tag='v1.0.1')
        self.assertEqual(self.legacy.read_bytes(), self.canonical.read_bytes())
        self.assertEqual((self.dest / 'telemt-web-manager.sh').read_bytes(), path.read_bytes())

    def legacy_pair(self):
        self.dest.mkdir(0o755); (self.dest / 'lib').mkdir(0o755)
        script = (ROOT / 'telemt-web-manager.sh').read_text().replace(
            '# Telegram Web Proxy Manager.', '# Telemt WEB Manager.').replace(
            'SCRIPT_VERSION=1.1.2', 'SCRIPT_VERSION=1.0.1')
        (self.dest / 'telemt-web-manager.sh').write_text(script)
        (self.dest / 'telemt-web-manager.sh').chmod(0o755)
        (self.dest / 'lib/safety.py').write_bytes((ROOT / 'lib/safety.py').read_bytes())
        (self.dest / 'lib/safety.py').chmod(0o644)
        self.legacy.write_text('#!/bin/sh\nexec ' + str(self.dest / 'telemt-web-manager.sh') + ' "$@"\n')
        self.legacy.chmod(0o755)

    def test_existing_legacy_101_pair_gains_canonical_command(self):
        self.legacy_pair(); old_wrapper = self.legacy.read_bytes()
        self.install(); self.assert_launchers()
        self.assertEqual(self.legacy.read_bytes(), old_wrapper)

    def test_unrelated_canonical_file_refuses_without_mutation(self):
        self.legacy_pair(); self.canonical.write_text('unrelated\n'); self.canonical.chmod(0o755)
        before = self.snapshot(); self.install(False); self.assertEqual(before, self.snapshot())

    def test_unsafe_canonical_paths_refuse_without_mutation(self):
        for kind in ('symlink', 'hardlink', 'mode', 'owner'):
            with self.subTest(kind=kind):
                self.canonical.unlink(missing_ok=True)
                if kind == 'symlink': self.canonical.symlink_to(self.source / 'safety.py')
                elif kind == 'hardlink': os.link(self.source / 'safety.py', self.canonical)
                else:
                    self.canonical.write_text('unrelated')
                    self.canonical.chmod(0o777 if kind == 'mode' else 0o755)
                    if kind == 'owner': os.chown(self.canonical, 65534, 65534)
                self.install(False)
                self.assertFalse(self.dest.exists()); self.assertFalse(self.legacy.exists())

    def test_second_launcher_failure_rolls_back_fresh_and_existing_pair(self):
        inject = '''import os
real_replace = os.replace
calls = 0
def fail_second(a, b):
    global calls
    calls += 1
    if calls == 2: raise OSError('second launcher publication failed')
    real_replace(a, b)
os.replace = fail_second
'''
        before = self.snapshot(); self.install(False, inject); self.assertEqual(before, self.snapshot())
        self.legacy_pair(); self.legacy.unlink()  # existing pair with neither wrapper
        before = self.snapshot(); self.install(False, inject); self.assertEqual(before, self.snapshot())

    def test_interruption_before_commit_preserves_legacy_pair(self):
        self.legacy_pair(); before = self.snapshot()
        inject = '''import os, signal, tempfile
real_mkstemp = tempfile.mkstemp
def interrupt_stage(*args, **kwargs):
    os.kill(os.getpid(), signal.SIGTERM)
    return real_mkstemp(*args, **kwargs)
tempfile.mkstemp = interrupt_stage
'''
        self.install(False, inject); self.assertEqual(before, self.snapshot())


class PublicBrand(unittest.TestCase):
    def test_current_public_files_and_version(self):
        for filename in ('README.md', 'README.en.md', 'README.ru.md', 'docs/OPERATIONS.md',
                         'docs/UPSTREAM.md', 'docs/CI-COVERAGE.md', 'telemt-web-manager.sh'):
            text = (ROOT / filename).read_text()
            self.assertNotIn('Telemt WEB Manager', text, filename)
        shell = (ROOT / 'telemt-web-manager.sh').read_text()
        helper = (ROOT / 'lib/safety.py').read_text()
        self.assertIn('readonly SCRIPT_VERSION=1.1.2', shell)
        self.assertIn("UPDATE_MANAGER_VERSION = '1.1.2'", helper)
        self.assertEqual(helper.count("'User-Agent': 'telegram-web-proxy-manager/1.1.2'"), 2)
        for filename in ('README.md', 'README.en.md'):
            text = (ROOT / filename).read_text()
            # Language navigation now precedes the centered project heading.
            self.assertIn('<h1 align="center">Telegram Web Proxy Manager</h1>', text)
            self.assertNotIn('xPROMSx/telemt-web-manager', text)
            self.assertIn('xPROMSx/telegram-web-proxy-manager/main/install.sh', text)
            self.assertIn('](docs/UPSTREAM.md)', text)
        # Recognition of old program headers is the explicit legacy ABI allowlist.
        self.assertEqual(helper.count('# Telemt WEB Manager.'), 1)
        self.assertEqual((ROOT / 'install.sh').read_text().count('# Telemt WEB Manager.'), 2)


if __name__ == '__main__':
    unittest.main(verbosity=2)
