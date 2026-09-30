import contextlib
import importlib.util
import io
import json
import os
import tarfile
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("safety", ROOT / "lib/safety.py")
s = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = s
spec.loader.exec_module(s)


class SafetyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "nginx"
        shutil.copytree(ROOT / "tests/fixtures/nginx", self.root)
        (self.root / "conf.d").mkdir()
        self.plan = Path(self.temp.name) / "plan.json"

    def snapshot(self):
        return {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def plan_nginx(self):
        s.nginx_plan(self.root, "proxy.example.com", self.plan)
        return json.loads(self.plan.read_text())

    def test_recognized_stream_and_idempotence(self):
        before = self.snapshot()
        plan = self.plan_nginx()
        self.assertEqual(before, self.snapshot(), "planning must be read-only")
        self.assertEqual(len(plan["edits"]), 2)
        for edit in plan["edits"]:
            Path(edit["path"]).write_text(edit["content"])
        content = (self.root / "stream.conf").read_text()
        self.assertIn("panel.example.com panel;", content)
        self.assertIn("default xray;", content)
        self.assertEqual(self.plan_nginx()["edits"], [])

    def test_unknown_map_refused_without_mutation(self):
        path = self.root / "stream.conf"
        path.write_text(path.read_text().replace("$ssl_preread_server_name", "$remote_addr"))
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.plan_nginx()
        self.assertEqual(before, self.snapshot())

    def test_no_proxy_protocol_refused(self):
        path = self.root / "stream.conf"
        path.write_text(path.read_text().replace("proxy_protocol on;", ""))
        with self.assertRaises(ValueError):
            self.plan_nginx()

    def test_duplicate_map_refused(self):
        with (self.root / "stream.conf").open("a") as out:
            out.write("map $ssl_preread_server_name $other { default xray; }")
        with self.assertRaises(ValueError):
            self.plan_nginx()

    def test_regex_map_refused(self):
        path = self.root / "stream.conf"
        path.write_text(path.read_text().replace("panel.example.com", "~.*example.com"))
        with self.assertRaises(ValueError):
            self.plan_nginx()

    def test_competing_listener_refused(self):
        (self.root / "conf.d/other.conf").write_text("server { listen 443 ssl; }")
        with self.assertRaises(ValueError):
            self.plan_nginx()

    def test_modified_managed_vhost_refused(self):
        for edit in self.plan_nginx()["edits"]:
            Path(edit["path"]).write_text(edit["content"])
        path = self.root / "conf.d/telemt-web-manager.conf"
        path.write_text(path.read_text().replace("access_log off", "access_log /tmp/access"))
        with self.assertRaises(ValueError):
            self.plan_nginx()

    def test_dns_a_and_real_aaaa(self):
        s.dns_check("203.0.113.10\n", "", "203.0.113.10")
        for a in ("", "203.0.113.11", "203.0.113.10\n203.0.113.11", "alias.example.com"):
            with self.assertRaises(ValueError):
                s.dns_check(a, "", "203.0.113.10")
        for aaaa in ("2001:db8::1", "::ffff:203.0.113.10"):
            with self.assertRaises(ValueError):
                s.dns_check("203.0.113.10", aaaa, "203.0.113.10")

    def test_known_warning_narrow_classification(self):
        line = "WARN Failed to reconcile conntrack firewall policy error=startup recovery failed: iptables v1.8.11 (nf_tables): Chain 'TELEMT_NOTRACK' does not exist"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(s.classify("3.5.9", "ubuntu:26.04", "nf_tables", line), 0)
            for version, os, backend in (("3.6.0", "ubuntu:26.04", "nf_tables"),
                                         ("3.5.9", "ubuntu:24.04", "nf_tables"),
                                         ("3.5.9", "ubuntu:26.04", "legacy")):
                self.assertEqual(s.classify(version, os, backend, line), 1)
            self.assertEqual(s.classify("3.5.9", "ubuntu:26.04", "nf_tables", line + "; Permission denied"), 1)
            self.assertEqual(s.classify("3.5.9", "ubuntu:26.04", "nf_tables", "ERROR Operation not permitted"), 1)

    def test_hostname_injection_refused(self):
        for host in ("../example.com", "x;example.com", 'x".example.com', "a\n.example.com"):
            with self.assertRaises(ValueError):
                s.domain(host)


class ThreeXTopologyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "nginx"
        shutil.copytree(ROOT / "tests/fixtures/nginx-3x-ui", self.root)
        (self.root / "conf.d").mkdir()
        self.plan = Path(self.temp.name) / "plan.json"
        self.stream = self.root / "stream-enabled/stream.conf"

    def snapshot(self):
        return {str(p): p.read_bytes() for p in self.root.rglob("*") if p.is_file()}

    def plan_nginx(self):
        s.nginx_plan(self.root, "proxy.example.com", self.plan)
        return json.loads(self.plan.read_text())

    def test_production_layout_preserves_routes_and_shared_http_files(self):
        before = self.snapshot()
        plan = self.plan_nginx()
        self.assertEqual(before, self.snapshot())
        self.assertEqual({x['path'] for x in plan['edits']},
                         {str(self.stream.resolve()), str(self.root / 'conf.d/telemt-web-manager.conf')})
        for edit in plan['edits']:
            Path(edit['path']).write_text(edit['content'])
        after = self.stream.read_text()
        self.assertEqual(after.count('proxy.example.com twm_frontend;'), 1)
        self.assertEqual(after.count('upstream twm_frontend'), 1)
        self.assertIn('listen     [::]:443;', after)
        mapping = "    proxy.example.com twm_frontend; # telemt-web-manager\n"
        upstream = "\n# telemt-web-manager\nupstream twm_frontend { server 127.0.0.1:7444; }\n"
        self.assertEqual(after.replace(mapping, '').replace(upstream, ''),
                         before[str(self.stream)].decode())
        for path, content in before.items():
            if path != str(self.stream):
                self.assertEqual(Path(path).read_bytes(), content)
        self.assertEqual(self.plan_nginx()['edits'], [])

    def test_unsafe_variants_refused_without_writes(self):
        original = self.stream.read_text()
        replacements = (
            ('hostnames;', 'hostnames; hostnames;'),
            ('hostnames;', 'hostnames extra;'),
            ('panel.example.com      www;', 'panel.example.com      www; hostnames;'),
            ('panel.example.com', '*.example.com'),
            ('panel.example.com', '.example.com'),
            ('panel.example.com', '~.*example.com'),
            ('set_real_ip_from unix:;', 'set_real_ip_from 0.0.0.0/0;'),
            ('set_real_ip_from unix:;', 'set_real_ip_from unix:; set_real_ip_from 127.0.0.1;'),
            ('listen     [::]:443;', 'listen [::]:443 proxy_protocol;'),
            ('listen     [::]:443;', 'listen [::]:443; listen [::]:443;'),
            ('listen     [::]:443;', 'listen [2001:db8::1]:443;'),
            ('listen     443;', 'listen 443 proxy_protocol;'),
            ('proxy_protocol on;', 'proxy_protocol off;'),
            ('proxy_protocol on;', 'proxy_protocol on; proxy_protocol off;'),
            ('ssl_preread on;', 'ssl_preread on; ssl_preread off;'),
            ('ssl_preread on;', 'ssl_preread on; resolver 127.0.0.1;'),
            ('proxy_pass $sni_name;', 'proxy_pass $unknown;'),
            ('listen     443;', r'listen \443;'),
        )
        for old, new in replacements:
            with self.subTest(new=new):
                self.stream.write_text(original.replace(old, new))
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    self.plan_nginx()
                self.assertEqual(before, self.snapshot())

    def test_cycles_still_refused(self):
        path = self.root / 'snippets/includes.conf'
        path.write_text('include snippets/includes.conf;')
        with self.assertRaises(ValueError):
            self.plan_nginx()

    def test_escaped_include_is_refused(self):
        path = self.root / 'sites-enabled/other.conf'
        path.write_text(r'include snippets/\*.conf;')
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.plan_nginx()
        self.assertEqual(before, self.snapshot())

    def test_escaped_http_cannot_hide_competing_listen(self):
        path = self.root / 'sites-enabled/other.conf'
        for directive in ('listen 443 ssl;', r'listen \443 ssl;', r'\listen 443 ssl;'):
            with self.subTest(directive=directive):
                path.write_text('server { ' + directive + ' }')
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    self.plan_nginx()
                self.assertEqual(before, self.snapshot())

    def test_malformed_quotes_are_refused(self):
        path = self.root / 'sites-enabled/other.conf'
        for text in ('server { set $x "unterminated; }', 'server { set $x "a"hidden; }'):
            path.write_text(text)
            with self.assertRaises(ValueError):
                self.plan_nginx()

    def test_acme_plan_preserves_redirect_and_is_idempotent(self):
        before = self.snapshot()
        s.acme_plan(self.root, 'proxy.example.com', self.plan, '/var/lib/twm-acme')
        plan = json.loads(self.plan.read_text())
        self.assertEqual(before, self.snapshot())
        self.assertEqual(len(plan['edits']), 1)
        edit = plan['edits'][0]
        Path(edit['path']).write_text(edit['content'])
        s.acme_plan(self.root, 'proxy.example.com', self.plan, '/var/lib/twm-acme')
        self.assertEqual(json.loads(self.plan.read_text())['edits'], [])
        s.nginx_plan(self.root, 'proxy.example.com', self.plan, '/var/lib/twm-acme')
        self.assertEqual(len(json.loads(self.plan.read_text())['edits']), 2)
        for path, content in before.items():
            self.assertEqual(Path(path).read_bytes(), content)

    def test_acme_conflicts_and_unrecognized_http_refused(self):
        path = self.root / 'sites-enabled/80.conf'
        original = path.read_text()
        for old, new in (('panel.example.com', 'proxy.example.com'),
                         ('panel.example.com', '*.example.com'),
                         ('listen 80;', 'listen 80 proxy_protocol;'),
                         ('listen 80;', 'listen 80; resolver 127.0.0.1;'),
                         ('return 301 https://$host$request_uri;', 'return 200 custom;')):
            with self.subTest(new=new):
                path.write_text(original.replace(old, new))
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    s.acme_plan(self.root, 'proxy.example.com', self.plan, '/var/lib/twm-acme')
                self.assertEqual(before, self.snapshot())

    def test_acme_modified_managed_vhost_refused(self):
        path = self.root / 'conf.d/telemt-web-manager-acme.conf'
        path.write_text(s.render_acme('proxy.example.com', '/var/lib/twm-acme').replace('return 404', 'return 200'))
        with self.assertRaises(ValueError):
            s.acme_plan(self.root, 'proxy.example.com', self.plan, '/var/lib/twm-acme')


class SecurityTests(unittest.TestCase):
    def test_socks_address_validation(self):
        for value in ('127.0.0.1:1080', 'localhost:1080', 'socks.example.com:65535'):
            s.socks_address(value)
        for value in ('127.0.0.1:0', '127.0.0.1:65536', '999.1.1.1:1080',
                      '-bad.example.com:1080', 'x\n.example.com:1080', '127.0.0.1:abc', '[::1]:1080'):
            with self.assertRaises(ValueError):
                s.socks_address(value)

    @unittest.skipUnless(os.name == 'posix', 'Unix archive/path flags are checked on Linux CI')
    def test_unsafe_archive_variants_never_create_binary(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / 'asset.tar.gz'
            output = Path(tmp) / 'binary'
            for name, kind, count in (('../telemt', tarfile.REGTYPE, 1), ('telemt', tarfile.SYMTYPE, 1),
                                      ('telemt', tarfile.LNKTYPE, 1), ('telemt', tarfile.DIRTYPE, 1),
                                      ('telemt', tarfile.REGTYPE, 2)):
                with tarfile.open(archive, 'w:gz') as tar:
                    for _ in range(count):
                        member = tarfile.TarInfo(name)
                        member.type = kind
                        if kind in (tarfile.SYMTYPE, tarfile.LNKTYPE):
                            member.linkname = '/bin/sh'
                        member.size = 7 if kind == tarfile.REGTYPE else 0
                        tar.addfile(member, io.BytesIO(b'fixture') if member.size else None)
                with self.assertRaises(ValueError):
                    s.extract_binary(archive, output)
                self.assertFalse(output.exists())

    @unittest.skipUnless(os.name == 'posix', 'Unix permissions checked on Linux CI')
    def test_symlink_and_writable_ancestor_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/'target').mkdir()
            (root/'link').symlink_to(root/'target')
            with self.assertRaises(ValueError):
                s.safe_path(root/'link/file')
            (root/'target').chmod(0o777)
            with self.assertRaises(ValueError):
                s.safe_path(root/'target/file')


if __name__ == "__main__":
    unittest.main()
