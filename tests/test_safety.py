import contextlib
import importlib.util
import io
import gzip
import json
import os
import pty
import subprocess
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

    def test_warning_payload_does_not_override_structural_severity(self):
        line = "WARN Failed to reconcile conntrack firewall policy error=startup recovery failed: iptables v1.8.11 (nf_tables): Chain 'TELEMT_NOTRACK' does not exist; Permission denied"
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(s.classify(line), 0)
            self.assertEqual(s.classify('ERROR WARN ' + line), 1)
            self.assertEqual(s.classify('FATAL WARN ' + line), 1)

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

    def run_shell_plan(self, host, *, terminal=False, term='xterm-256color', no_color=False):
        script = '''source "$1/telemt-web-manager.sh"
NGINX_ROOT=$2 DOMAIN=$3 TMP=$4
nginx_plan
printf 'INSTALL_CONTINUED\\n'
'''
        env = dict(os.environ, TERM=term)
        env.pop('NO_COLOR', None)
        if no_color:
            env['NO_COLOR'] = ''
        args = ['bash', '-c', script, 'fixture', str(ROOT), str(self.root), host, self.temp.name]
        if not terminal:
            result = subprocess.run(args, env=env, capture_output=True, timeout=15)
            return result.returncode, result.stdout + result.stderr
        master, slave = pty.openpty()
        try:
            with os.fdopen(slave, 'wb') as output:
                result = subprocess.run(args, env=env, stdout=subprocess.PIPE, stderr=output, timeout=15)
            captured = result.stdout
            while True:
                try:
                    chunk = os.read(master, 4096)
                except OSError as error:
                    if error.errno != 5:  # Linux PTY EOF.
                        raise
                    break
                if not chunk:
                    break
                captured += chunk
            return result.returncode, captured.replace(b'\r\n', b'\n')
        finally:
            os.close(master)

    def test_occupied_domain_diagnostic_is_fixed_private_and_color_aware(self):
        reality = self.root/'sites-enabled/reality.conf'
        reality.write_text(reality.read_text() + '\n# PRIVATE_PASSWORD tg://webproxy?secret=PRIVATE_SECRET\n')
        before = self.snapshot()
        expected = ('ERROR: This domain is already used in Nginx (possibly by 3x-ui / REALITY).\n'
                    'Use a separate, unused domain or subdomain for Telegram WEB.\n'
                    'No Nginx configuration was changed.\n').encode()
        for terminal, term, no_color, color in (
                (False, 'xterm-256color', False, False), (True, 'xterm-256color', False, True),
                (True, 'xterm-256color', True, False), (True, 'dumb', False, False),
                (True, '', False, False), (True, 'unknown', False, False)):
            with self.subTest(terminal=terminal, term=term, no_color=no_color):
                code, output = self.run_shell_plan('reality.example.com', terminal=terminal,
                                                   term=term, no_color=no_color)
                self.assertEqual(code, 1)
                self.assertEqual(output, b'\x1b[1;31m' + expected[:-1] + b'\x1b[0m\n' if color else expected)
                self.assertNotIn(b'INSTALL_CONTINUED', output)
                self.assertNotIn(b'PRIVATE_', output)
                self.assertNotIn(b'automatic nginx integration not possible', output)
                self.assertEqual(before, self.snapshot())
                self.assertFalse((Path(self.temp.name)/'nginx-plan.json').exists())

    def test_free_domain_shell_plan_still_succeeds_read_only(self):
        before = self.snapshot()
        code, output = self.run_shell_plan('proxy.example.com')
        self.assertEqual((code, output), (0, b'INSTALL_CONTINUED\n'))
        self.assertEqual(before, self.snapshot())
        self.assertEqual(len(json.loads((Path(self.temp.name)/'nginx-plan.json').read_text())['edits']), 2)

    def test_other_unsafe_plan_keeps_generic_secret_safe_refusal(self):
        self.stream.write_text(self.stream.read_text().replace('$ssl_preread_server_name', '$remote_addr')
                               + '\n# PRIVATE_PASSWORD tg://webproxy?secret=PRIVATE_SECRET\n')
        before = self.snapshot()
        code, output = self.run_shell_plan('proxy.example.com')
        self.assertEqual(code, 1)
        self.assertEqual(output, b'Safety validation failed; manual review required (no credentials displayed).\n'
                                b'ERROR: automatic nginx integration not possible\n')
        self.assertEqual(before, self.snapshot())
        self.assertFalse((Path(self.temp.name)/'nginx-plan.json').exists())

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
            ('upstream xray {', 'resolver 127.0.0.1; upstream xray {'),
            ('server 127.0.0.1:8443;', 'server 127.0.0.1:8443; least_conn;'),
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

    @staticmethod
    def webroot_http():
        return """server {
    listen 80;
    listen [::]:80;
    server_name panel.example.com reality.example.com;
    location ^~ /.well-known/acme-challenge/ {
        root /var/www/acme;
        default_type text/plain;
        try_files $uri =404;
    }
    location / {
        return 301 https://$host$request_uri;
    }
}
"""

    def test_acme_plan_preserves_webroot_redirect_and_is_idempotent(self):
        path = self.root / 'sites-enabled/80.conf'
        path.write_text(self.webroot_http())
        before = self.snapshot()
        acme = self.root / 'conf.d/telemt-web-manager-acme.conf'
        own_root = '/var/lib/telemt-web-manager-acme'
        s.acme_plan(self.root, 'proxy.example.com', self.plan, own_root)
        plan = json.loads(self.plan.read_text())
        self.assertEqual(before, self.snapshot())
        self.assertEqual(plan['edits'], [dict(path=str(acme), content=s.render_acme('proxy.example.com', own_root), old=None)])
        for edit in plan['edits']: Path(edit['path']).write_text(edit['content'])
        s.acme_plan(self.root, 'proxy.example.com', self.plan, own_root)
        self.assertEqual(json.loads(self.plan.read_text())['edits'], [])
        for name, raw in before.items(): self.assertEqual(Path(name).read_bytes(), raw)

    def test_acme_webroot_unknown_routing_refused_without_mutation(self):
        original = self.webroot_http()
        path = self.root / 'sites-enabled/80.conf'
        cases = (
            ('root /var/www/acme;', 'root /wrong;'),
            ('root /var/www/acme;', 'root $document_root;'),
            ('root /var/www/acme;', 'alias /var/www/acme;'),
            ('default_type text/plain;', ''),
            ('default_type text/plain;', 'default_type text/html;'),
            ('try_files $uri =404;', ''),
            ('try_files $uri =404;', 'try_files $uri =200;'),
            ('try_files $uri =404;', 'try_files $uri /index.html =404;'),
            ('try_files $uri =404;', 'proxy_pass http://127.0.0.1;'),
            ('try_files $uri =404;', 'fastcgi_pass 127.0.0.1:9000;'),
            ('try_files $uri =404;', 'grpc_pass grpc://127.0.0.1;'),
            ('try_files $uri =404;', 'return 404;'),
            ('root /var/www/acme;', 'root /var/www/acme; add_header X-Test yes;'),
            ('root /var/www/acme;', 'root /var/www/acme; rewrite ^ /other;'),
            ('root /var/www/acme;', 'root /var/www/acme; if ($uri) { return 404; }'),
            ('root /var/www/acme;', 'root /var/www/acme; location /nested { return 404; }'),
            ('/.well-known/acme-challenge/', '/.well-known/other/'),
            ('location ^~', 'location'),
            ('return 301', 'return 302'),
            ('return 301', 'return 200'),
            ('https://$host$request_uri', 'https://panel.example.com$request_uri'),
            ('panel.example.com', 'proxy.example.com'),
            ('panel.example.com', '*.example.com'),
            ('panel.example.com', '~^panel'),
            ('listen 80;', 'listen 80 proxy_protocol;'),
            ('listen 80;', 'listen 80 ssl;'),
            ('listen 80;', 'listen 80 default_server;'),
            ('listen 80;', 'listen 80 reuseport;'),
            ('listen 80;', 'listen 80; listen 127.0.0.1:80;'),
            ('listen [::]:80;', ''),
            ('location / {', 'location /extra { return 404; } location / {'),
            ('listen 80;', 'listen 80; resolver 127.0.0.1;'),
            ('listen 80;', 'listen 80; include snippets/webroot-empty.conf;'),
            ('root /var/www/acme;', 'root /var/www/acme; include snippets/webroot-empty.conf;'),
            ('panel.example.com reality.example.com', 'panel.example.com panel.example.com'),
        )
        snippet = self.root / 'snippets/webroot-empty.conf'
        snippet.write_text('# No directives, but includes are not trusted in this profile.\n')
        variants = [original.replace(old, new) for old, new in cases]
        variants.append(original + original)
        for text in variants:
            with self.subTest(text=text):
                path.write_text(text); self.plan.unlink(missing_ok=True)
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    s.acme_plan(self.root, 'proxy.example.com', self.plan, '/var/lib/telemt-web-manager-acme')
                self.assertEqual(before, self.snapshot())
                self.assertFalse((self.root / 'conf.d/telemt-web-manager-acme.conf').exists())
                if self.plan.exists():
                    self.assertTrue(all(not edit['path'].endswith('/telemt-web-manager-acme.conf')
                                        for edit in json.loads(self.plan.read_text())['edits']))

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
            member = tarfile.TarInfo('telemt')
            member.size = 128 * 1024 * 1024 + 1
            with gzip.open(archive, 'wb') as compressed:
                compressed.write(member.tobuf() + b'\0' * 1024)
            with self.assertRaises(ValueError):
                s.extract_binary(archive, output)
            self.assertFalse(output.exists())

    @unittest.skipUnless(os.name == 'posix', 'Unix flags checked on Linux CI')
    def test_archive_output_symlink_does_not_overwrite_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = root/'target'
            target.write_bytes(b'unchanged')
            output = root/'binary'
            output.symlink_to(target)
            archive = root/'asset.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                member = tarfile.TarInfo('telemt')
                member.size = 7
                tar.addfile(member, io.BytesIO(b'fixture'))
            with self.assertRaises(OSError):
                s.extract_binary(archive, output)
            self.assertEqual(target.read_bytes(), b'unchanged')

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
