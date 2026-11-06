"""3X-UI PR #93 includes topology, PR #99 REALITY fallback, and TWPM ownership."""
import json
from pathlib import Path
import shutil
import tempfile
import unittest
from test_safety import ROOT, s


class IncludeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'nginx'
        shutil.copytree(ROOT / 'tests/fixtures/nginx-3x-includes', self.root)
        for name in ('conf.d', 'stream-sni.d', 'stream-upstreams.d', 'snippets/x-ui-auto-optional'):
            (self.root / name).mkdir(parents=True, exist_ok=True)
            (self.root / name).chmod(0o755)
        self.output = Path(self.tmp.name) / 'plan.json'
        self.host = 'proxy.example.com'

    def snapshot(self):
        return {p.relative_to(self.root): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}

    def plan(self, uninstall=False, site_digest=None):
        s.nginx_plan(self.root, self.host, self.output, uninstall=uninstall, site_digest=site_digest)
        return json.loads(self.output.read_text())

    def apply(self, plan):
        for edit in plan['edits']:
            path = Path(edit['path'])
            if edit['content'] is None: s.planned_unlink(str(self.output), str(path))
            else:
                path.write_text(edit['content'])
                path.chmod(0o644)

    def test_pr99_http_origin_install_check_uninstall_preserves_neighbor(self):
        stream = self.root / 'stream-enabled/stream.conf'
        self.assertIn('server 127.0.0.1:8443 max_fails=0;', stream.read_text())
        self.assertIn('server 127.0.0.1:9443 backup;', stream.read_text())
        before = self.snapshot()
        digest = s.site_generate(Path(self.tmp.name) / 'site', 'night-sky')
        install = self.plan(site_digest=digest)
        self.assertEqual(len(install['edits']), 3)
        self.assertEqual(self.snapshot(), before)
        self.apply(install)
        self.assertEqual(self.plan()['edits'], [])
        vhost = self.root / 'conf.d/telemt-web-manager.conf'
        self.assertEqual(vhost.read_text(), s.render_vhost(self.host, site_digest=digest))
        self.assertIn('listen 127.0.0.1:18081;', vhost.read_text())
        self.apply(self.plan(uninstall=True))
        self.assertEqual(self.snapshot(), before)

    def test_pr99_preserves_historical_single_server_xray(self):
        stream = self.root / 'stream-enabled/stream.conf'
        original = stream.read_text()
        stream.write_text(original.replace(
            'upstream xray {\n    server 127.0.0.1:8443 max_fails=0;\n'
            '    server 127.0.0.1:9443 backup;\n}',
            'upstream xray { server 127.0.0.1:8443; }'))
        before = self.snapshot()
        self.apply(self.plan())
        self.assertEqual(self.plan()['edits'], [])
        self.apply(self.plan(uninstall=True))
        self.assertEqual(self.snapshot(), before)

    def test_pr99_refuses_unknown_stream_upstreams_without_mutation(self):
        stream = self.root / 'stream-enabled/stream.conf'
        original = stream.read_text()
        reviewed = ('upstream xray {\n'
                    '    server 127.0.0.1:8443 max_fails=0;\n'
                    '    server 127.0.0.1:9443 backup;\n}')
        self.assertIn(reviewed, original)
        invalid = (
            reviewed.replace('max_fails=0', 'max_fails=1'),
            reviewed.replace('127.0.0.1:9443', '127.0.0.1:9444'),
            reviewed.replace('9443 backup;', '9443 max_fails=0 backup;'),
            reviewed.replace('8443 max_fails=0;', '8443;'),
            reviewed.replace('9443 backup;', '9443;'),
            reviewed.replace('    server 127.0.0.1:9443 backup;\n', ''),
            reviewed.replace('    server 127.0.0.1:9443 backup;\n',
                             '    server 127.0.0.1:9443 backup;\n'
                             '    server 127.0.0.1:10555 backup;\n'),
            reviewed + '\nupstream foreign { server 127.0.0.1:8443 max_fails=0; '
                       'server 127.0.0.1:9443 backup; }',
        )
        for variant in invalid:
            with self.subTest(variant=variant):
                stream.write_text(original.replace(reviewed, variant))
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    self.plan(site_digest='a' * 64)
                self.assertEqual(self.snapshot(), before)
        stream.write_text(original)
        self.apply(self.plan())
        twm = self.root / 'stream-upstreams.d/telemt-web-manager.conf'
        twm.write_text('upstream twm_frontend { server 127.0.0.1:7444; '
                       'server 127.0.0.1:9443 backup; }\n')
        before = self.snapshot()
        for uninstall in (False, True):
            with self.assertRaises(ValueError):
                self.plan(uninstall=uninstall)
            self.assertEqual(self.snapshot(), before)

    def test_include_install_check_immutable_uninstall_preserves_neighbor(self):
        before = self.snapshot()
        plan = self.plan()
        self.assertEqual(len(plan['edits']), 3)
        self.assertEqual(self.snapshot(), before)
        self.apply(plan)
        self.assertEqual(self.plan()['edits'], [])
        parser = s.Nginx(self.root)
        stream = s.exact(parser.read(self.root / 'nginx.conf'), 'stream')[0]
        owned, _ = s.nginx_owned_stream(parser, self.host, stream)
        self.assertEqual(set(owned), {'nginx-map', 'nginx-upstream'})
        for p, content in before.items(): self.assertEqual((self.root / p).read_bytes(), content)
        self.apply(self.plan(uninstall=True))
        self.assertEqual(self.snapshot(), before)
        for name in ('stream-sni.d', 'stream-upstreams.d'): self.assertTrue((self.root / name).is_dir())

    def test_parser_preserves_map_context_across_includes(self):
        (self.root / 'stream-sni.d/neighbor.conf').write_text('other.example.com www;\n')
        self.assertEqual(len(self.plan()['edits']), 3)

    def test_legacy_does_not_migrate_when_includes_appear(self):
        stream = self.root / 'stream-enabled/stream.conf'
        new = stream.read_text()
        stream.write_text('\n'.join(x for x in new.splitlines() if 'stream-sni.d' not in x and 'stream-upstreams.d' not in x) + '\n')
        self.apply(self.plan())
        parser = s.Nginx(self.root)
        owned_before = s.nginx_owned_stream(parser, self.host,
                       s.exact(parser.read(self.root / 'nginx.conf'), 'stream')[0])[0]
        old = stream.read_text()
        stream.write_text(old.replace('    default', '    include stream-sni.d/*.conf;\n    default').replace('server {\n', 'include stream-upstreams.d/*.conf;\nserver {\n'))
        installed = stream.read_bytes()
        self.assertEqual(self.plan()['edits'], [])
        self.assertEqual(stream.read_bytes(), installed)
        parser = s.Nginx(self.root)
        self.assertEqual(s.nginx_owned_stream(parser, self.host,
                         s.exact(parser.read(self.root / 'nginx.conf'), 'stream')[0])[0], owned_before)
        self.assertFalse((self.root / 'stream-sni.d/telemt-web-manager.conf').exists())
        self.apply(self.plan(uninstall=True))
        self.assertNotIn('twm_frontend', stream.read_text())
        self.assertIn('include stream-sni.d/*.conf;', stream.read_text())

    def test_changed_or_partial_includes_are_never_adopted_or_removed(self):
        self.apply(self.plan())
        original = self.snapshot()
        variants = [
            ('stream-sni.d/telemt-web-manager.conf', 'proxy.example.com twm_frontend; # changed\n'),
            ('stream-upstreams.d/telemt-web-manager.conf', 'upstream twm_frontend { server 127.0.0.1:7445; }\n'),
            ('stream-sni.d/telemt-web-manager.conf', ''),
            ('stream-upstreams.d/telemt-web-manager.conf', None),
            ('stream-sni.d/duplicate.conf', 'proxy.example.com twm_frontend;\n'),
            ('stream-upstreams.d/duplicate.conf', 'upstream twm_frontend { server 127.0.0.1:7444; }\n'),
            ('stream-sni.d/foreign.conf', 'other.example.com twm_frontend;\n'),
        ]
        for name, content in variants:
            with self.subTest(name=name, content=content):
                for p in list(self.root.rglob('*.conf')):
                    if p.relative_to(self.root) not in original: p.unlink()
                for p, data in original.items(): (self.root / p).write_bytes(data)
                path = self.root / name
                if content is None: path.unlink()
                else: path.write_text(content)
                before = self.snapshot()
                for uninstall in (False, True):
                    with self.assertRaises(ValueError): self.plan(uninstall)
                    self.assertEqual(before, self.snapshot())

    def test_missing_partial_duplicate_or_misplaced_contract_refused(self):
        stream = self.root / 'stream-enabled/stream.conf'
        original = stream.read_text()
        for content in (original.replace('include stream-sni.d/*.conf;', ''),
                        original.replace('include stream-sni.d/*.conf;', 'include stream-sni.d/*.conf; include stream-sni.d/*.conf;'),
                        original.replace('include stream-sni.d/*.conf;', '').replace('include stream-upstreams.d/*.conf;', 'include stream-upstreams.d/*.conf; include stream-sni.d/*.conf;')):
            with self.subTest(content=content):
                stream.write_text(content)
                with self.assertRaises(ValueError): self.plan()
        stream.write_text(original)
        (self.root / 'stream-sni.d').rmdir()
        with self.assertRaises(ValueError): self.plan()

    def test_shared_directory_permissions_and_owned_hardlinks_refused(self):
        directory = self.root / 'stream-sni.d'
        directory.chmod(0o700)
        with self.assertRaises(ValueError): self.plan()
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        directory.chmod(0o755)
        self.apply(self.plan())
        path = directory / 'telemt-web-manager.conf'
        (directory / 'unrelated.data').hardlink_to(path)
        before = self.snapshot()
        for uninstall in (False, True):
            with self.assertRaises(ValueError): self.plan(uninstall)
            self.assertEqual(self.snapshot(), before)

    def test_mixed_inline_include_format_refused_without_mutation(self):
        self.apply(self.plan())
        row = self.root / 'stream-sni.d/telemt-web-manager.conf'
        row.unlink()
        stream = self.root / 'stream-enabled/stream.conf'
        stream.write_text(stream.read_text().replace('    default',
                          '    proxy.example.com twm_frontend; # telemt-web-manager\n    default'))
        before = self.snapshot()
        for uninstall in (False, True):
            with self.assertRaises(ValueError): self.plan(uninstall)
            self.assertEqual(self.snapshot(), before)
