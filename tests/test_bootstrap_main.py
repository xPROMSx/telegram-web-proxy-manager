"""Real isolated bootstrap install, with only HTTPS transport replaced by fixtures."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SHA = 'a' * 40
REPO = 'xPROMSx/telegram-web-proxy-manager'


@unittest.skipUnless(os.geteuid() == 0, 'root-owned installation fixture')
class MainInstall(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix='main-bootstrap-', dir='/var/tmp')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('opt', 'bin', 'lock', 'fixtures'):
            (self.root / name).mkdir(0o700)
        f = self.root / 'fixtures'
        f.joinpath('repository').write_text(json.dumps(dict(id=1398514078,
            full_name=REPO, name='telegram-web-proxy-manager', html_url='https://github.com/'+REPO,
            owner=dict(id=102687702, login='xPROMSx'), private=False, fork=False, archived=False, disabled=False)))
        f.joinpath('ref').write_text(json.dumps(dict(ref='refs/heads/main', object=dict(type='commit', sha=SHA))))
        release = dict(tag_name='v1.1.1', draft=False, prerelease=False,
                       published_at='2026-10-01T00:00:00Z', html_url='https://github.com/'+REPO+'/releases/tag/v1.1.1')
        f.joinpath('releases').write_text(json.dumps([release]))
        f.joinpath('release').write_text(json.dumps(release))
        f.joinpath('tag').write_text(json.dumps(dict(ref='refs/tags/v1.1.1', object=dict(type='commit', sha=SHA))))
        self.candidate('1.1.0')

    def candidate(self, version):
        f = self.root / 'fixtures'
        text = (ROOT / 'telemt-web-manager.sh').read_text()
        import re
        text = re.sub(r'^readonly SCRIPT_VERSION=.*$', 'readonly SCRIPT_VERSION='+version, text, flags=re.M)
        f.joinpath('shell').write_text(text+'\ntouch "'+str(self.root / 'executed')+'"\n')
        text = re.sub(r"^UPDATE_MANAGER_VERSION = .*$", "UPDATE_MANAGER_VERSION = '"+version+"'", (ROOT / 'lib/safety.py').read_text(), flags=re.M)
        f.joinpath('helper').write_text(text+'\nopen('+repr(str(self.root / 'executed'))+', "w").write("executed")\n')

    def run_install(self, success=True, *args):
        script = r'''source "$1"
INSTALL_DIR=$2/opt/manager; LAUNCHER=$2/bin/telemt-web-manager
BOOTSTRAP_LOCK=$2/lock/manager; MANAGER_STATE=$2/state; MANAGER_SYSTEMD_ROOT=$2/systemd
FIXTURE=$2/fixtures; REQUESTS=$2/requests
bootstrap_repository_metadata() { cp "$FIXTURE/repository" "$2"; printf 200; }
bootstrap_download() {
    printf '%s\n' "$1" >>"$REQUESTS"
    case $1 in
        */git/ref/heads/main)
            cp "$FIXTURE/ref" "$2" || return 1
            if [[ -e $FIXTURE/../advance ]]; then
                sed -i 's/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb/' "$FIXTURE/ref"
            fi;;
        */releases\?*) cp "$FIXTURE/releases" "$2";;
        */releases/tags/v1.1.1) cp "$FIXTURE/release" "$2";;
        */git/ref/tags/v1.1.1) cp "$FIXTURE/tag" "$2";;
        https://raw.githubusercontent.com/xPROMSx/telegram-web-proxy-manager/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/telemt-web-manager.sh) cp "$FIXTURE/shell" "$2";;
        https://raw.githubusercontent.com/xPROMSx/telegram-web-proxy-manager/aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa/lib/safety.py) cp "$FIXTURE/helper" "$2";;
        *) return 1;;
    esac
}
shift 2; bootstrap_main --no-start "$@"
'''
        result = subprocess.run(['bash', '-c', script, 'fixture', str(ROOT / 'install.sh'), str(self.root), *args], capture_output=True, timeout=20)
        self.assertEqual(result.returncode == 0, success, result.stderr.decode())
        self.assertFalse((self.root / 'executed').exists(), 'candidate executed')
        if success:
            self.assertEqual((self.root / 'opt/manager/telemt-web-manager.sh').read_bytes(), (self.root / 'fixtures/shell').read_bytes())
            self.assertEqual((self.root / 'opt/manager/lib/safety.py').read_bytes(), (self.root / 'fixtures/helper').read_bytes())
        return result

    def test_release_111_content_110_does_not_block_main_install(self):
        result = self.run_install()
        self.assertIn(b'Installed manager 1.1.0', result.stdout)
        self.assertIn(SHA.encode(), result.stdout)
        calls = (self.root / 'requests').read_text()
        self.assertNotIn('/releases', calls)
        self.assertNotIn('/git/ref/tags/', calls)

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mode,
                    p.stat().st_uid, p.stat().st_gid)
                for name in ('opt', 'bin') for p in (self.root / name).rglob('*') if p.is_file()}

    def assert_main_only(self):
        calls = (self.root / 'requests').read_text().splitlines()
        self.assertFalse(any('/releases' in p or '/git/ref/tags/' in p for p in calls))
        self.assertEqual(sum('/git/ref/heads/main' in p for p in calls), 1)
        self.assertEqual([p for p in calls if 'raw.githubusercontent' in p], [
            'https://raw.githubusercontent.com/'+REPO+'/'+SHA+'/telemt-web-manager.sh',
            'https://raw.githubusercontent.com/'+REPO+'/'+SHA+'/lib/safety.py'])

    def test_no_releases_high_release_and_unavailable_release_api_are_irrelevant(self):
        f = self.root / 'fixtures'
        for content in ('[]', '[{"tag_name":"v999.0.0"}]', 'unavailable'):
            with self.subTest(content=content):
                (self.root / 'requests').unlink(missing_ok=True)
                f.joinpath('releases').write_text(content)
                f.joinpath('release').unlink(missing_ok=True)
                f.joinpath('tag').unlink(missing_ok=True)
                self.run_install(); self.assert_main_only()

    def test_main_advance_does_not_mix_pair(self):
        # Transport updates the branch metadata immediately after returning its
        # original SHA. The second download still has to use the frozen SHA.
        self.root.joinpath('advance').touch()
        self.run_install(); self.assert_main_only()
        self.assertEqual(json.loads(self.root.joinpath('fixtures/ref').read_text())['object']['sha'], 'b'*40)

    def test_bad_main_metadata_preserves_installation(self):
        self.run_install(); before = self.snapshot()
        ref = self.root / 'fixtures/ref'
        good = dict(ref='refs/heads/main', object=dict(type='commit', sha=SHA))
        cases = [dict(good, ref='refs/heads/foreign'), dict(good, object=dict(type='tag', sha=SHA)),
                 dict(good, object=dict(type='commit', sha='oops')), dict(good, object=None),
                 dict(good, object=dict(type='commit', sha=1)), [], {}, '{',
                 '{"ref":"refs/heads/main","ref":"refs/heads/main"}']
        for value in cases:
            with self.subTest(value=value):
                ref.write_text(value if isinstance(value, str) else json.dumps(value))
                self.run_install(False); self.assertEqual(before, self.snapshot())

    def test_wrong_repository_or_owner_refuses_without_mutation(self):
        self.run_install(); before = self.snapshot()
        p = self.root / 'fixtures/repository'; good = json.loads(p.read_text())
        for changes in (dict(id=1), dict(full_name='attacker/foreign'), dict(owner=dict(login='attacker', id=102687702)), dict(owner=dict(login='xPROMSx', id=1))):
            with self.subTest(changes=changes):
                p.write_text(json.dumps(good | changes))
                self.run_install(False); self.assertEqual(before, self.snapshot())

    def test_network_and_invalid_pair_preserve_installed_manager(self):
        self.run_install(); before = self.snapshot(); f = self.root / 'fixtures'
        for file, content in (('ref', None), ('shell', None), ('helper', None),
                              ('shell', ''), ('helper', ''), ('shell', 'if then'),
                              ('helper', 'if :'), ('shell', '#!/bin/bash\ntouch ignored'),
                              ('helper', 'print("foreign")')):
            with self.subTest(file=file, content=content):
                saved = f.joinpath(file).read_bytes()
                if content is None: f.joinpath(file).unlink()
                else: f.joinpath(file).write_text(content)
                self.run_install(False); self.assertEqual(before, self.snapshot())
                f.joinpath(file).write_bytes(saved)
        for suffix in ("\nUPDATE_MANAGER_VERSION = '99.0.0'\n", "\nUPDATE_MANAGER_VERSION = str(99)\n"):
            saved = f.joinpath('helper').read_bytes()
            f.joinpath('helper').write_bytes(saved + suffix.encode())
            self.run_install(False); self.assertEqual(before, self.snapshot())
            f.joinpath('helper').write_bytes(saved)

    def test_reinstall_upgrade_and_actual_version_downgrade_guard(self):
        self.run_install(); before = self.snapshot()
        self.run_install(); self.assertEqual(before, self.snapshot())
        self.candidate('1.1.2'); self.run_install()
        before = self.snapshot()
        self.candidate('1.1.0'); result = self.run_install(False)
        self.assertIn(b'automatic downgrade refused', result.stderr)
        self.assertEqual(before, self.snapshot())
        # An explicit tag identifies the source, not the installed version. This
        # historical tag has mismatched contents; report the actual version.
        result = self.run_install(True, '--version', 'v1.1.1')
        self.assertIn(b'Installed manager 1.1.0', result.stdout)
        self.assertNotIn(b'Installed manager v1.1.1', result.stdout)

    def test_release_preparation_rejects_original_111_vs_110_mismatch(self):
        repo = self.root / 'release-prep'; repo.mkdir()
        repo.joinpath('tests').mkdir(); repo.joinpath('lib').mkdir()
        repo.joinpath('install.sh').write_bytes((ROOT / 'install.sh').read_bytes())
        repo.joinpath('tests/bootstrap_versions.sh').write_bytes((ROOT / 'tests/bootstrap_versions.sh').read_bytes())
        repo.joinpath('telemt-web-manager.sh').write_bytes(self.root.joinpath('fixtures/shell').read_bytes())
        repo.joinpath('lib/safety.py').write_bytes(self.root.joinpath('fixtures/helper').read_bytes())
        result = subprocess.run(['bash', str(repo / 'tests/bootstrap_versions.sh'), '--release-tag', 'v1.1.1'], capture_output=True, timeout=10)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(b'Release target does not match', result.stderr)
        self.assertFalse(self.root.joinpath('executed').exists())
