"""Known Fresh baselines keep their original identities across manager updates."""
import ast
import copy
from pathlib import Path
import unittest
from unittest.mock import patch
import update_transactions as t

s = t.s
ROOT = Path(__file__).resolve().parents[1]
PINS = {
    '3.5.12': ('c4555e25f39dd5be200ccf6353f7d82bfcf89131', {
        'x86_64': ('92bfaa6177d87790bae79caea08d8ddddd0ca3ebc95545c1d62374897592c6c3', '53da315a9f61975913235f72c4adb413313089b966ffcca700653b4663d3d964'),
        'aarch64': ('16bfd0e78b746171b0434c935ca953358c88b43cfb0091d7b74cb982424202a3', '308271c73ece5d748aeab21680c10c2bea153ba29c83135b1b84aa79a394173c')}),
    '3.5.16': ('84e5b827a6619fb2e09ad3d09f253cdffe04bc2f', {
        'x86_64': ('e6f46b2f3becf29bfd555cec8a059e429f7c082c1af402499b3a7940cf8ebd34', '1954f18faeb9f5838e9444880f2ffb00704c6bd5b2836bc86dd64611537d49b8'),
        'aarch64': ('1e1bc87f05923b9673cbbaf34a3e50f7fdcf7d496cd24efcdb34c278ed18a659', 'ebaec212fd5556ceca7fb0fcc4d3d23c01a8883d20a4cbc567219022d57c2a0b')})}


def receipt(version, arch):
    commit, pins = PINS[version]
    return dict(schema=1, origin='reviewed-baseline', repository=dict(s.UPSTREAM_REPOSITORY),
        architecture=arch, installed_version=version, tag=version, tag_object_sha=None,
        commit_sha=commit, tag_verification=None, release=None, asset=None, checksum_asset=None,
        archive_sha256=pins[arch][0], binary=dict(sha256=pins[arch][1], size=123),
        installed_at='2026-10-31T12:00:00Z', manager_version='1.1.2', transaction_id='1'*32,
        generation_id='2'*32, trust_policy='embedded-reviewed-baseline-v1')


def bootstrap_validator():
    text=next(block.split('\nPY\n',1)[0] for block in (ROOT/'install.sh').read_text().split("cat <<'PY'\n")[1:] if 'def recovery_receipt' in block.split('\nPY\n',1)[0])
    tree=ast.parse(text)
    nodes=[n for n in tree.body if isinstance(n,(ast.Import,ast.ImportFrom)) or
           isinstance(n,ast.FunctionDef) and n.name.startswith('recovery_')]
    namespace={}
    exec(compile(ast.Module(body=nodes,type_ignores=[]), 'installed-bootstrap-validator', 'exec'),namespace)
    return namespace['recovery_receipt']


def assert_bootstrap_accepts_baselines(baselines):
    validate = bootstrap_validator()
    for version, (commit, pins) in baselines.items():
        for arch, (archive, binary) in pins.items():
            value = dict(schema=1, origin='reviewed-baseline', repository=dict(s.UPSTREAM_REPOSITORY),
                architecture=arch, installed_version=version, tag=version, tag_object_sha=None,
                commit_sha=commit, tag_verification=None, release=None, asset=None, checksum_asset=None,
                archive_sha256=archive, binary=dict(sha256=binary, size=123),
                installed_at='2026-10-31T12:00:00Z', manager_version='1.1.2', transaction_id='1'*32,
                generation_id='2'*32, trust_policy='embedded-reviewed-baseline-v1')
            try:
                validate(value)
            except ValueError as error:
                raise AssertionError(
                    f'install.sh bootstrap rejected reviewed baseline {version} for {arch}') from error


class BaselineVersions(unittest.TestCase):
    def test_bootstrap_accepts_all_helper_reviewed_baselines(self):
        assert_bootstrap_accepts_baselines(s.REVIEWED_BASELINES)

    def test_bootstrap_baseline_check_reports_synthetic_drift(self):
        for arch in ('x86_64', 'aarch64'):
            with self.subTest(arch=arch), self.assertRaisesRegex(
                    AssertionError, rf'install\.sh bootstrap rejected reviewed baseline 9\.9\.9 for {arch}'):
                assert_bootstrap_accepts_baselines({'9.9.9': ('a'*40, {arch: ('b'*64, 'c'*64)})})

    def test_both_validators_accept_original_baselines_and_reject_crossed_pins(self):
        for validate in (s.UpdateReceipt.validate, bootstrap_validator()):
            for version in PINS:
                for arch in ('x86_64','aarch64'):
                    good=receipt(version,arch); before=copy.deepcopy(good)
                    validate(good); self.assertEqual(good,before)
                    for key in ('installed_version','commit_sha','archive_sha256','binary'):
                        bad=copy.deepcopy(good)
                        other='3.5.16' if version=='3.5.12' else '3.5.12'
                        bad[key]=receipt(other,arch)[key]
                        if key=='installed_version': bad['tag']=bad[key]
                        with self.subTest(version=version,arch=arch,key=key),self.assertRaises(ValueError): validate(bad)
                    bad=copy.deepcopy(good); bad['installed_version']=bad['tag']='3.5.15'
                    with self.assertRaises(ValueError): validate(bad)

    def test_creation_uses_exact_binary_identity_not_current_default(self):
        for version, (_,pins) in PINS.items():
            for arch, (_,digest) in pins.items():
                with patch.object(s,'update_hash',return_value=dict(sha256=digest,size=123)):
                    value=s.UpdateReceipt.create(Path('/fixture'), '1'*32,'2'*32, arch=arch)
                self.assertEqual(value,receipt(version,arch)|{'installed_at':value['installed_at'],
                                                            'manager_version':'1.3.2'})
                bootstrap_validator()(value)
        with patch.object(s,'update_hash',return_value=dict(sha256='f'*64,size=123)):
            with self.assertRaises(ValueError): s.UpdateReceipt.create(Path('/fixture'),'1'*32,'2'*32,arch='x86_64')

    def test_receiptless_recognition_is_readonly_and_migration_is_explicit(self):
        for version in PINS:
            with self.subTest(version=version):
                f=t.Fixture(); self.addCleanup(f.close)
                s.update_remove_gate(f.layout)
                for path in (f.layout.receipt,f.layout.journal,f.layout.generation,f.layout.data/'.telemt-web-manager-generation.json'): path.unlink()
                actual_hash=s.update_hash
                def binary_hash(path,*args,**kwargs):
                    return dict(sha256=PINS[version][1]['x86_64'][1],size=123) if Path(path)==f.layout.binary else actual_hash(path,*args,**kwargs)
                with patch.object(s,'update_hash',side_effect=binary_hash):
                    value=f.engine.local_receipt(allow_legacy=True)
                    self.assertEqual(value['installed_version'],version)
                    self.assertFalse(f.layout.receipt.exists()); self.assertFalse(f.layout.journal.exists())
                    f.engine.migrate(value)
                    self.assertEqual(f.engine.local_receipt()['installed_version'],version)
                self.assertEqual(f.layout.config.read_bytes(),b'unchanged managed TOML')

    def test_equal_reviewed_versions_bind_own_identity_and_downgrade_is_refused(self):
        for version in PINS:
            f=t.Fixture(version=version); self.addCleanup(f.close)
            reviewed=receipt(version,'x86_64'); s.UpdateReceipt.validate(reviewed)
            release=f.engine.releases.freeze(f.engine.releases.latest(),'x86_64')
            release.update(commit_sha=reviewed['commit_sha'])
            release['asset']['sha256']=reviewed['archive_sha256']
            with patch.object(f.engine,'local_receipt',return_value=reviewed), \
                 patch.object(f.controller,'identity',return_value={}), \
                 patch.object(f.engine.releases,'freeze',return_value=release), \
                 patch.object(f.engine.releases,'download') as download:
                before=f.engine.tree.inventory(f.layout.data)
                f.engine.update()
                self.assertEqual(f.engine.tree.inventory(f.layout.data),before)
                download.assert_not_called()
                release['commit_sha']='f'*40
                with self.assertRaises(ValueError): f.engine.update()
                if version=='3.5.16':
                    f.engine.releases.version='3.5.13'
                    with self.assertRaises(ValueError): f.engine.update()
                download.assert_not_called()
