"""A foreign DoT listener can coexist with both supported stream layouts."""
import hashlib
from itertools import product
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from test_safety import ROOT, s


HOST = 'proxy.example.com'
PROFILES = ('nginx-3x-ui', 'nginx-3x-includes')
DOT = (ROOT / 'tests/fixtures/nginx-dot.conf').read_text()


def add_dot(root, *, inline=False, block=DOT):
    main = root / 'nginx.conf'
    config = main.read_text()
    anchor = ('include stream-enabled/*.conf;' if 'include stream-enabled/*.conf;' in config
              else 'include stream.conf;')
    if inline:
        path, addition = main, block
    else:
        path = root / 'neighbor-services/dns.conf'
        path.parent.mkdir(exist_ok=True)
        path.write_text(block)
        addition = 'include neighbor-services/*.conf;\n'
    main.write_text(config.replace(anchor, anchor + '\n' + addition, 1))
    return path


class DotTests(unittest.TestCase):
    def fixture(self, profile):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        base = Path(temp.name)
        root = base / 'nginx'
        shutil.copytree(ROOT / 'tests/fixtures' / profile, root)
        for path in ('conf.d', 'stream-sni.d', 'stream-upstreams.d', 'snippets/x-ui-auto-optional'):
            directory = root / path
            directory.mkdir(parents=True, exist_ok=True)
            directory.chmod(0o755)
        return root, base / 'plan.json'

    def snapshot(self, root):
        return {path: path.read_bytes() for path in root.rglob('*') if path.is_file()}

    def plan(self, root, output, **kwargs):
        s.nginx_plan(root, HOST, output, **kwargs)
        return json.loads(output.read_text())

    def apply(self, output, plan):
        for edit in plan['edits']:
            path = Path(edit['path'])
            if edit['content'] is None:
                s.planned_unlink(str(output), edit['path'])
            else:
                path.write_text(edit['content'])
                path.chmod(0o644)

    def manifest(self, root, output):
        vhost = root / 'conf.d/telemt-web-manager.conf'
        manifest = output.with_name('manifest.json')
        manifest.write_text(json.dumps(dict(
            schema=1, domain=HOST, public_ip='203.0.113.10', unit_sha256='1' * 64,
            nginx_sha256=hashlib.sha256(vhost.read_bytes()).hexdigest(), acme_webroot='',
        )))
        manifest.chmod(0o600)
        return manifest

    def test_dot_fresh_install_rerun_check_and_uninstall_preserve_foreign_bytes(self):
        dual_stack = DOT.replace('listen 853 ssl;', 'listen 853 ssl;\n    listen [::]:853 ssl;')
        dual_stack = dual_stack.replace('limit_conn dot_conn 50;', 'limit_conn dot_conn 17;\n    proxy_timeout 15s;')
        for profile, inline, block in product(PROFILES, (False, True), (DOT, dual_stack)):
            with self.subTest(profile=profile, inline=inline, dual_stack=block == dual_stack):
                root, output = self.fixture(profile)
                dot = add_dot(root, inline=inline, block=block)
                before = self.snapshot(root)
                fresh = self.plan(root, output, site_digest='a' * 64, site_port=18086)
                self.assertTrue(fresh['edits'])
                self.assertNotIn(str(dot), {edit['path'] for edit in fresh['edits']})
                self.apply(output, fresh)
                self.assertEqual(dot.read_bytes(), before[dot])

                # Rerun Install, Check and Repair share this installed plan.
                repeat = self.plan(root, output, manifest=self.manifest(root, output))
                self.assertEqual(repeat['edits'], [])
                self.apply(output, repeat)
                self.assertEqual(dot.read_bytes(), before[dot])

                uninstall = self.plan(root, output, uninstall=True)
                self.assertTrue(uninstall['edits'])
                self.assertNotIn(str(dot), {edit['path'] for edit in uninstall['edits']})
                self.apply(output, uninstall)
                self.assertEqual(self.snapshot(root), before)

    def test_dot_without_limit_zone_accepts_second_stream_server(self):
        root, output = self.fixture(PROFILES[0])
        block = '\n'.join(line for line in DOT.splitlines() if 'limit_conn' not in line) + '\n'
        add_dot(root, block=block)
        self.assertTrue(self.plan(root, output)['edits'])

    def test_dot_keeps_acme_and_legacy_keepalive_plans_available(self):
        for profile, inline, operation in product(PROFILES, (False, True), ('acme', 'keepalive')):
            with self.subTest(profile=profile, inline=inline, operation=operation):
                root, output = self.fixture(profile)
                self.apply(output, self.plan(root, output))
                dot = add_dot(root, inline=inline)
                webroot = str(output.with_name('acme'))
                vhost = root / 'conf.d/telemt-web-manager.conf'
                if operation == 'keepalive':
                    vhost.write_bytes((ROOT / 'tests/fixtures/nginx-vhost-legacy.conf').read_bytes())
                    manifest = self.manifest(root, output)
                    planner = s.nginx_keepalive_plan
                    args = (manifest,)
                else:
                    vhost = root / 'conf.d/telemt-web-manager-acme.conf'
                    planner = s.acme_plan
                    args = ()
                before = self.snapshot(root)
                planner(root, HOST, output, webroot, *args)
                plan = json.loads(output.read_text())
                self.assertEqual([edit['path'] for edit in plan['edits']], [str(vhost)])
                self.assertEqual(plan['snapshot'][str(dot)], hashlib.sha256(before[dot]).hexdigest())
                self.assertEqual(self.snapshot(root), before)

    def test_stream_listener_and_context_refusals(self):
        for block in ('server { listen 0.0.0.0:443; }', 'server { listen [::]:443; }',
                      'server { listen 127.0.0.1:443; }', 'server { listen 7444; }',
                      'server { listen 18080; }', 'server { listen 18086; }',
                      'server { listen $unresolved; }', 'proxy_timeout 15s;'):
            with self.subTest(block=block):
                root, output = self.fixture(PROFILES[0])
                add_dot(root, block=block)
                before = self.snapshot(root)
                with self.assertRaises(s.SafetyRefusal):
                    self.plan(root, output, site_digest='a' * 64, site_port=18086)
                self.assertFalse(output.exists())
                self.assertEqual(self.snapshot(root), before)

    def test_stream_without_443_router_refuses(self):
        root, output = self.fixture(PROFILES[0])
        router = root / 'stream-enabled/stream.conf'
        router.write_text(router.read_text().replace('443;', '444;'))
        before = self.snapshot(root)
        with self.assertRaises(s.SafetyRefusal):
            self.plan(root, output)
        self.assertFalse(output.exists())
        self.assertEqual(self.snapshot(root), before)
