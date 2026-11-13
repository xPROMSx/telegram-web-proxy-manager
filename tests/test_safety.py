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
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("safety", ROOT / "lib/safety.py")
s = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = s
spec.loader.exec_module(s)


class HelperRefusalTests(unittest.TestCase):
    def helper(self, *args, input=None):
        return subprocess.run([sys.executable, str(ROOT/'lib/safety.py'), *args],
                              input=input, capture_output=True, timeout=10)

    def test_require_without_message_reports_exact_caller_location(self):
        with self.assertRaises(s.SafetyRefusal) as caught:
            line = sys._getframe().f_lineno + 1
            s.require(False)
        self.assertEqual(str(caught.exception),
                         'test_require_without_message_reports_exact_caller_location:'+str(line))
        result = self.helper('semver', '1.0.0-01')
        self.assertEqual((result.returncode, result.stdout), (1, b''))
        self.assertRegex(result.stderr, rb'^Safety validation failed \(semver:[0-9]+\); manual review required \(no credentials displayed\)\.\n$')

    def test_require_message_and_domain_refusal_are_specific(self):
        with self.assertRaises(s.SafetyRefusal) as caught:
            s.require(False, 'fixed test reason')
        self.assertEqual(str(caught.exception), 'fixed test reason')
        result = self.helper('domain', 'Proxy.Example.com')
        self.assertEqual((result.returncode, result.stdout), (1, b''))
        self.assertEqual(result.stderr, b'Safety validation failed (invalid domain (use lowercase ASCII/punycode)); manual review required (no credentials displayed).\n')

    def test_safety_refusal_preserves_russian_presentation_scope(self):
        from web_link_fixture import terminal
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory)/'state'; state.mkdir(mode=0o755)
            cases = [('update-universal', ['invalid'], 'update_command'),
                     ('update-recover', ['invalid'], 'update_command'),
                     ('web-link-display', [str(state), str(Path(directory)/'config')], 'current_web_link')]
            for command, args, function in cases:
                for language in ('ru', 'en'):
                    with self.subTest(command=command, language=language):
                        env = dict(os.environ, TWM_UI_LANGUAGE=language, TERM='dumb')
                        code, output = terminal([sys.executable, str(ROOT/'lib/safety.py'), command, *args], env=env)
                        self.assertEqual(code, 1)
                        reason = function + r':[0-9]+'
                        expected = (r'^Проверка безопасности не пройдена \(' + reason +
                                    r'\)\. Автоматическое изменение остановлено; требуется ручная проверка\. Секреты не показаны\.\n$'
                                    if language == 'ru' else
                                    r'^Safety validation failed \(' + reason +
                                    r'\); manual review required \(no credentials displayed\)\.\n$')
                        self.assertRegex(output.decode(), expected)
            code, output = terminal([sys.executable, str(ROOT/'lib/safety.py'), 'domain', 'Example.invalid'],
                                    env=dict(os.environ, TWM_UI_LANGUAGE='ru', TERM='dumb'))
            self.assertEqual(code, 1)
            self.assertEqual(output, b'Safety validation failed (invalid domain (use lowercase ASCII/punycode)); manual review required (no credentials displayed).\n')

    def test_malformed_toml_and_json_keep_generic_secret_safe_refusal(self):
        import tomllib
        cases = [('config-info', 'private="PRIVATE_REFUSAL_MARKER"\nbroken=[', tomllib.loads),
                 ('classify-journal', '{"private":"PRIVATE_REFUSAL_MARKER",', json.loads)]
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'broken.toml'
            for command, raw, parser in cases:
                with self.subTest(command=command):
                    with self.assertRaises(ValueError) as caught: parser(raw)
                    path.write_text(raw)
                    result = (self.helper(command, str(path)) if command == 'config-info'
                              else self.helper(command, input=raw.encode()))
                    self.assertEqual((result.returncode, result.stdout), (1, b''))
                    self.assertEqual(result.stderr, b'Safety validation failed; manual review required (no credentials displayed).\n')
                    self.assertNotIn(b'PRIVATE_REFUSAL_MARKER', result.stderr)
                    self.assertNotIn(str(caught.exception).encode(), result.stderr)

    def test_accept_retains_fixed_readiness_deadline(self):
        engine = object.__new__(s.UpdateEngine)
        engine.systemd = Mock()
        engine.systemd.show.return_value = {'ActiveState':'active', 'NRestarts':'0'}
        engine.systemd.identity.side_effect = lambda receipt: s.require(False, 'running executable pathname mismatch')
        with patch.object(s.time, 'monotonic', side_effect=[0, 91]):
            with self.assertRaisesRegex(s.SafetyRefusal, '^Telemt identity/listener readiness deadline$'):
                engine.accept({})


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

    def test_fresh_web_backend_reuses_http_connections(self):
        vhost=next(edit['content'] for edit in self.plan_nginx()['edits']
                   if Path(edit['path']).name=='telemt-web-manager.conf')
        self.assertIn('upstream twpm_web_backend {\n    server 127.0.0.1:18080;\n    keepalive 32;\n}',vhost)
        self.assertIn('proxy_pass http://twpm_web_backend;',vhost)
        self.assertIn('proxy_http_version 1.1;',vhost)
        self.assertIn('proxy_set_header Connection "";',vhost)

    def test_unknown_map_refused_without_mutation(self):
        path = self.root / "stream.conf"
        path.write_text(path.read_text().replace("$ssl_preread_server_name", "$remote_addr"))
        before = self.snapshot()
        with self.assertRaises(ValueError):
            self.plan_nginx()
        self.assertEqual(before, self.snapshot())

    def test_stream_hash_bucket_preserved_and_idempotent(self):
        path = self.root / 'stream.conf'
        path.write_text('map_hash_bucket_size 272;\n' + path.read_text())
        before = self.snapshot()
        plan = self.plan_nginx()
        self.assertEqual(before, self.snapshot())
        self.assertEqual(len(plan['edits']), 2)
        for edit in plan['edits']: Path(edit['path']).write_text(edit['content'])
        self.assertTrue(path.read_text().startswith('map_hash_bucket_size 272;\n'))
        self.assertEqual(self.plan_nginx()['edits'], [])

    def test_stream_hash_bucket_unsafe_variants_refused_without_mutation(self):
        path = self.root / 'stream.conf'
        original = path.read_text()
        variants = [directive + original for directive in (
            'map_hash_bucket_size 128;\n', 'map_hash_bucket_size 272 extra;\n',
            'map_hash_bucket_size;\n', 'map_hash_bucket_size 272 {}\n',
            'map_hash_bucket_size 272; map_hash_bucket_size 272;\n',
            'map_hash_max_size 272;\n')]
        variants.append(original.replace('proxy_protocol on;',
                                         'proxy_protocol on; map_hash_bucket_size 272;'))
        for text in variants:
            with self.subTest(text=text):
                path.write_text(text)
                self.plan.unlink(missing_ok=True)
                before = self.snapshot()
                with self.assertRaises(ValueError): self.plan_nginx()
                self.assertEqual(before, self.snapshot())
                self.assertFalse(self.plan.exists())

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

    def run_shell_plan(self, host, *, terminal=False, term='xterm-256color', no_color=False,
                       helper_body=None):
        script = '''source "$1/telemt-web-manager.sh"
NGINX_ROOT=$2 DOMAIN=$3 TMP=$4
'''
        if helper_body is not None:
            script += 'helper() { ' + helper_body + '; }\n'
        script += '''nginx_plan
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

    def test_other_unsafe_plan_names_check_without_disclosing_secrets(self):
        self.stream.write_text(self.stream.read_text().replace('$ssl_preread_server_name', '$remote_addr')
                               + '\n# PRIVATE_PASSWORD tg://webproxy?secret=PRIVATE_SECRET\n')
        before = self.snapshot()
        code, output = self.run_shell_plan('proxy.example.com')
        self.assertEqual(code, 1)
        self.assertRegex(output, rb'^Safety validation failed \(nginx_plan:[0-9]+\); manual review required \(no credentials displayed\)\.\n$')
        self.assertNotIn(b'PRIVATE_', output)
        self.assertEqual(before, self.snapshot())
        self.assertFalse((Path(self.temp.name)/'nginx-plan.json').exists())

    def test_shell_plan_retains_one_message_for_reported_and_silent_failures(self):
        for body, expected in (
                ("printf 'fixed helper refusal\\n' >&2; return 7", b'fixed helper refusal\n'),
                ('return 7', b'ERROR: automatic nginx integration not possible\n')):
            with self.subTest(body=body):
                before = self.snapshot()
                code, output = self.run_shell_plan('proxy.example.com', helper_body=body)
                self.assertEqual((code, output), (7, expected))
                self.assertNotIn(b'INSTALL_CONTINUED', output)
                self.assertEqual(before, self.snapshot())

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
                         ('listen 80;', 'listen 80; listen 80;')):
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

    def vision_topology(self):
        # Semantic output of assets/vision/managed.py at immutable 3x-ui commit
        # b1fd00282a887456d974c29e74891c017235050b; upstream is never executed.
        (self.root / 'sites-enabled/80.conf').write_text(self.webroot_http())
        self.stream.write_text(self.stream.read_text().replace(
            '    hostnames;\n', '    hostnames;\n    vision.example.com vision;\n')
            + '\nupstream vision { server 127.0.0.1:10443; }\n')
        (self.root / 'sites-enabled/vision.conf').write_text("""server {
    listen 127.0.0.1:10444 proxy_protocol;
    server_name vision.example.com;
    server_tokens off;
    root /var/www/html;
    index index.html;
    real_ip_header proxy_protocol;
    set_real_ip_from 127.0.0.1;
    if ($host != vision.example.com) { return 404; }
    location / { try_files $uri $uri/ =404; }
}
""")
        path = self.root / 'sites-enabled/vision-acme.conf'
        path.write_text(self.webroot_http().replace(
            'panel.example.com reality.example.com', 'vision.example.com').replace(
            '        default_type text/plain;\n', ''))
        return path

    def test_vision_acme_without_default_type_preserves_foreign_topology(self):
        self.vision_topology()
        before = self.snapshot()
        metadata = {str(p): (p.lstat().st_mode, p.lstat().st_uid, p.lstat().st_gid)
                    for p in self.root.rglob('*')}
        # WEB/SNI already accepts Vision; the RED is specifically acme_plan().
        self.assertEqual(len(self.plan_nginx()['edits']), 2)
        self.assertEqual(before, self.snapshot())
        own_root = '/var/lib/telemt-web-manager-acme'
        acme = self.root / 'conf.d/telemt-web-manager-acme.conf'
        try:
            s.acme_plan(self.root, 'proxy.example.com', self.plan, own_root)
        finally:
            self.assertEqual(before, self.snapshot())
            self.assertEqual(metadata, {str(p): (p.lstat().st_mode, p.lstat().st_uid, p.lstat().st_gid)
                                       for p in self.root.rglob('*')})
        self.assertEqual(json.loads(self.plan.read_text())['edits'],
                         [dict(path=str(acme), content=s.render_acme('proxy.example.com', own_root), old=None)])
        acme.write_text(s.render_acme('proxy.example.com', own_root))
        s.acme_plan(self.root, 'proxy.example.com', self.plan, own_root)
        self.assertEqual(json.loads(self.plan.read_text())['edits'], [])
        for name, raw in before.items(): self.assertEqual(Path(name).read_bytes(), raw)
        # Include the WEB integration as an already-installed deployment, then
        # prove both planners stay idempotent and never change foreign files.
        for edit in self.plan_nginx()['edits']: Path(edit['path']).write_text(edit['content'])
        installed = self.snapshot()
        self.assertEqual(self.plan_nginx()['edits'], [])
        s.acme_plan(self.root, 'proxy.example.com', self.plan, own_root)
        self.assertEqual(json.loads(self.plan.read_text())['edits'], [])
        self.assertEqual(installed, self.snapshot())

    def test_external_webroot_without_plain_type_is_allowed_without_vision(self):
        (self.root / 'sites-enabled/80.conf').write_text(
            self.webroot_http().replace('        default_type text/plain;\n', ''))
        before = self.snapshot()
        s.acme_plan(self.root, 'proxy.example.com', self.plan, '/var/lib/telemt-web-manager-acme')
        self.assertEqual(before, self.snapshot())
        self.assertEqual(len(json.loads(self.plan.read_text())['edits']), 1)

    def test_vision_acme_with_explicit_plain_type_preserves_foreign_topology(self):
        path = self.vision_topology()
        path.write_text(path.read_text().replace('root /var/www/acme;',
                                                 'root /var/www/acme; default_type text/plain;'))
        before = self.snapshot()
        own_root = '/var/lib/telemt-web-manager-acme'
        s.acme_plan(self.root, 'proxy.example.com', self.plan, own_root)
        self.assertEqual(before, self.snapshot())
        self.assertEqual(json.loads(self.plan.read_text())['edits'], [dict(
            path=str(self.root / 'conf.d/telemt-web-manager-acme.conf'),
            content=s.render_acme('proxy.example.com', own_root), old=None)])

    def test_current_3x_host_guard_is_foreign_content(self):
        # setup_acme_http(), 3X-UI 994414f54322712ba30fc03af21bee0a2c2c4f5f.
        self.webroot_http()
        path=self.root/'sites-enabled/80.conf'
        original=(ROOT/'tests/fixtures/nginx-http80-3x.conf').read_text()
        for ipv6 in (True,False):
            path.write_text(original if ipv6 else original.replace('    listen [::]:80;\n',''))
            before=self.snapshot()
            self.plan_nginx()
            s.nginx_plan(self.root,'proxy.example.com',self.plan,site_digest='a'*64)
            s.acme_plan(self.root,'proxy.example.com',self.plan,'/var/lib/telemt-web-manager-acme')
            edits=json.loads(self.plan.read_text())['edits']
            self.assertEqual([e['path'] for e in edits],[str(self.root/'conf.d/telemt-web-manager-acme.conf')])
            self.assertEqual(before,self.snapshot())
            Path(edits[0]['path']).write_text(edits[0]['content'])
            s.acme_plan(self.root,'proxy.example.com',self.plan,'/var/lib/telemt-web-manager-acme')
            self.assertEqual(json.loads(self.plan.read_text())['edits'],[])
            for name,raw in before.items(): self.assertEqual(Path(name).read_bytes(),raw)
            Path(edits[0]['path']).unlink()

    def test_vision_acme_ipv4_only_preserves_foreign_topology(self):
        self.vision_topology()
        originals = {self.root / 'sites-enabled' / name:
                     (self.root / 'sites-enabled' / name).read_text()
                     for name in ('80.conf', 'vision-acme.conf')}
        for plain_type in (False, True):
            with self.subTest(default_type=plain_type):
                for path, text in originals.items():
                    text = text.replace('    listen [::]:80;\n', '')
                    if plain_type and path.name == 'vision-acme.conf':
                        text = text.replace('root /var/www/acme;', 'root /var/www/acme; default_type text/plain;')
                    path.write_text(text)
                before = self.snapshot()
                own_root = '/var/lib/telemt-web-manager-acme'
                self.assertEqual(len(self.plan_nginx()['edits']), 2)
                s.acme_plan(self.root, 'proxy.example.com', self.plan, own_root)
                self.assertEqual(before, self.snapshot())
                acme = self.root / 'conf.d/telemt-web-manager-acme.conf'
                self.assertEqual(json.loads(self.plan.read_text())['edits'], [dict(
                    path=str(acme), content=s.render_acme('proxy.example.com', own_root), old=None)])
                acme.write_text(s.render_acme('proxy.example.com', own_root))
                s.acme_plan(self.root, 'proxy.example.com', self.plan, own_root)
                self.assertEqual(json.loads(self.plan.read_text())['edits'], [])
                for name, raw in before.items(): self.assertEqual(Path(name).read_bytes(), raw)
                acme.unlink()

    def test_vision_acme_unsafe_variants_and_occupied_domains_refused(self):
        path = self.vision_topology()
        original = path.read_text()
        cases = (("listen 80;", "listen 80; listen 80;"),)
        for old, new in cases:
            with self.subTest(replacement=new):
                path.write_text(original.replace(old, new)); self.plan.unlink(missing_ok=True)
                before = self.snapshot()
                with self.assertRaises(ValueError):
                    s.acme_plan(self.root, 'proxy.example.com', self.plan, '/var/lib/telemt-web-manager-acme')
                self.assertEqual(before, self.snapshot())
                self.assertTrue(all(not e['path'].endswith('/telemt-web-manager-acme.conf')
                                    for e in json.loads(self.plan.read_text())['edits']))
        path.write_text(original)
        before = self.snapshot()
        for host in ('vision.example.com', 'panel.example.com'):
            with self.subTest(host=host), self.assertRaises(s.NginxDomainInUse):
                s.acme_plan(self.root, host, self.plan, '/var/lib/telemt-web-manager-acme')
            self.assertEqual(before, self.snapshot())

    def test_acme_webroot_unknown_routing_refused_without_mutation(self):
        original = self.webroot_http()
        path = self.root / 'sites-enabled/80.conf'
        cases = (
            ('panel.example.com', 'proxy.example.com'),
            ('panel.example.com', '*.example.com'),
            ('panel.example.com', '~^panel'),
            ('listen 80;', 'listen 80 proxy_protocol;'),
            ('listen 80;', 'listen 80 ssl;'),
            ('listen 80;', 'listen 80 default_server;'),
            ('listen 80;', 'listen 80 reuseport;'),
            ('listen 80;', 'listen 80; listen 127.0.0.1:80;'),
            ('listen 80;', ''),  # IPv6-only remains unsupported; IPv6 is optional.
            ('listen 80;', 'listen 80; listen 80;'),
            ('listen [::]:80;', 'listen [::]:80; listen [::]:80;'),
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

    def test_foreign_http_bodies_do_not_control_twpm_challenge(self):
        original=self.webroot_http()
        path=self.root/'sites-enabled/80.conf'
        snippet=self.root/'snippets/webroot-empty.conf'; snippet.write_text('# empty\n')
        cases=(
            ('listen 80;', 'listen 80; include snippets/webroot-empty.conf;'),
            ('listen 80;', 'listen 80; resolver 127.0.0.1;'),
            ('root /var/www/acme;', 'root /wrong;'),
            ('root /var/www/acme;', 'root $document_root;'),
            ('root /var/www/acme;', 'alias /var/www/acme;'),
            ('default_type text/plain;', 'default_type text/html;'),
            ('default_type text/plain;', 'default_type text/plain; default_type text/plain;'),
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
            ('listen 80;', 'listen 0.0.0.0:80;'),
            ('location / {', 'location /extra { return 404; } location / {'),
            ('root /var/www/acme;', 'root /var/www/acme; include snippets/webroot-empty.conf;'),
        )
        for old,new in cases:
            with self.subTest(replacement=new):
                path.write_text(original.replace(old,new))
                before=self.snapshot()
                s.acme_plan(self.root,'proxy.example.com',self.plan,'/var/lib/telemt-web-manager-acme')
                self.assertEqual(before,self.snapshot())
                self.assertEqual(len(json.loads(self.plan.read_text())['edits']),1)

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


class FreshInstallInputTests(unittest.TestCase):
    def test_helper_domain_still_refuses_uppercase(self):
        result = subprocess.run([sys.executable, str(ROOT/'lib/safety.py'), 'domain',
                                 'Proxy.Example.com'], capture_output=True, timeout=5)
        self.assertEqual((result.returncode, result.stdout), (1, b''))

    def test_cname_chain_accepts_only_the_single_expected_ipv4(self):
        for a in ('203.0.113.10\n', 'target.example.com.\n203.0.113.10\n',
                  'edge_cache.example.com.\n203.0.113.10\n',
                  'First.Example.COM.\nlast.example.com.\n203.0.113.10\n'):
            for aaaa in ('', 'target.example.com.\nlast.example.com.\n'):
                with self.subTest(a=a, aaaa=aaaa):
                    s.dns_check(a, aaaa, '203.0.113.10')

    def test_dns_refusal_reasons_distinguish_the_existing_failures(self):
        for a, aaaa, reason in (
            ('target.example.com.\n', '', 'DNS A missing'),
            ('target.example.com.\n203.0.113.11', '', 'DNS A points to another IPv4'),
            ('203.0.113.10\n203.0.113.11', '', 'DNS A has multiple IPv4 addresses'),
            ('203.0.113.10\n203.0.113.10', '', 'DNS A has multiple IPv4 addresses'),
            ('203.0.113.10', 'target.example.com.\n2001:db8::1', 'DNS AAAA exists'),
        ):
            with self.subTest(a=a, aaaa=aaaa), self.assertRaisesRegex(ValueError, reason):
                s.dns_check(a, aaaa, '203.0.113.10')

    def test_cname_dns_preflight_keeps_two_existing_queries(self):
        with tempfile.TemporaryDirectory() as directory:
            code = '''source "$1"
TMP=$2 DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10
dig() {
    printf '%s\\n' "$*" >>"$TMP/queries"
    printf 'target.example.com.\\n'
    if [[ $4 == A ]]; then printf '203.0.113.10\\n'; fi
}
dns_preflight
'''
            result = subprocess.run(['bash', '-c', code, 'fixture',
                str(ROOT/'telemt-web-manager.sh'), directory], capture_output=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr.decode())
            self.assertEqual((Path(directory)/'queries').read_text().splitlines(), [
                '+time=3 +tries=1 +short A proxy.example.com',
                '+time=3 +tries=1 +short AAAA proxy.example.com'])

    def test_new_and_old_configs_pass_runtime_contract_without_rewriting(self):
        import tomllib
        result = subprocess.run(['bash', '-c', 'source "$1"; DOMAIN=proxy.example.com; '
            'PUBLIC_IP=203.0.113.10; generate_config "$2"', 'fixture',
            str(ROOT/'telemt-web-manager.sh'), '0123456789abcdef0123456789abcdef'],
            capture_output=True, check=True, timeout=5)
        self.assertEqual(tomllib.loads(result.stdout.decode())['general']['links'], {'show': []})
        self.assertIn(b'[general.links]\nshow = []\n', result.stdout)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/'config.toml'
            for content in (result.stdout, result.stdout.replace(b'[general.links]\nshow = []\n', b'')):
                path.write_bytes(content)
                checked = subprocess.run([sys.executable, str(ROOT/'lib/safety.py'),
                    'runtime-contract', str(path), '/var/lib/telemt'], capture_output=True, timeout=5)
                self.assertEqual(checked.returncode, 0, checked.stderr.decode())
                self.assertEqual(path.read_bytes(), content)

    def test_nginx_remnant_reasons_name_fixed_paths_without_contents(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)/'nginx'
            shutil.copytree(ROOT/'tests/fixtures/nginx', root)
            (root/'conf.d').mkdir()
            vhost = root/'conf.d/telemt-web-manager.conf'
            vhost.write_text('# PRIVATE_REMNANT tg://webproxy?secret=PRIVATE_SECRET\n')
            before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
            with self.assertRaises(ValueError) as caught:
                s.nginx_plan(root, 'proxy.example.com', Path(directory)/'plan')
            reason = str(caught.exception)
            self.assertIn('/etc/nginx/conf.d/telemt-web-manager.conf', reason)
            self.assertIn('другого сервера', reason)
            self.assertIn('another server', reason)
            self.assertNotIn('PRIVATE_', reason)
            self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('*') if p.is_file()})
            self.assertFalse((Path(directory)/'plan').exists())

    def test_partial_and_changed_nginx_remnants_keep_specific_reasons(self):
        for scenario, expected in (
            ('stream-only', '/etc/nginx'), ('wrong-map', '/etc/nginx'),
            ('wrong-upstream', '/etc/nginx'), ('changed-vhost', '/etc/nginx/conf.d/telemt-web-manager.conf'),
            ('orphan-include', '/etc/nginx/stream-sni.d/telemt-web-manager.conf')):
            with self.subTest(scenario=scenario), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)/'nginx'
                shutil.copytree(ROOT/'tests/fixtures/nginx', root)
                (root/'conf.d').mkdir()
                output = Path(directory)/'plan'
                s.nginx_plan(root, 'proxy.example.com', output)
                if scenario == 'orphan-include':
                    path = root/'stream-sni.d/telemt-web-manager.conf'
                    path.parent.mkdir(); path.write_text('PRIVATE_REMNANT')
                else:
                    for edit in json.loads(output.read_text())['edits']:
                        if scenario != 'stream-only' or Path(edit['path']).name != 'telemt-web-manager.conf':
                            Path(edit['path']).write_text(edit['content'])
                    path = root/'conf.d/telemt-web-manager.conf' if scenario == 'changed-vhost' else root/'stream.conf'
                    text = path.read_text()
                    if scenario == 'wrong-map': text = text.replace('proxy.example.com twm_frontend;', 'proxy.example.com panel;')
                    if scenario == 'wrong-upstream': text = text.replace('127.0.0.1:7444', '127.0.0.1:7445')
                    if scenario == 'changed-vhost': text = text.replace('client_max_body_size 2m', 'client_max_body_size 3m')
                    path.write_text(text)
                output.unlink()
                before = {p: p.read_bytes() for p in root.rglob('*') if p.is_file()}
                with self.assertRaises(ValueError) as caught:
                    s.nginx_plan(root, 'proxy.example.com', output)
                self.assertIn(expected, str(caught.exception))
                self.assertIn('другого сервера', str(caught.exception))
                self.assertNotIn('PRIVATE_REMNANT', str(caught.exception))
                self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('*') if p.is_file()})
                self.assertFalse(output.exists())

                manifest = Path(directory)/'manifest.json'
                manifest.write_text('{}')
                for context in ({'uninstall': True}, {'keepalive': True}, {'manifest': manifest}):
                    with self.subTest(context=context), self.assertRaises(ValueError) as installed:
                        s.nginx_plan(root, 'proxy.example.com', output, **context)
                    reason = str(installed.exception)
                    self.assertIn(expected, reason)
                    self.assertIn('manual review', reason)
                    self.assertIn('ручная проверка', reason)
                    self.assertIn("Let's Encrypt", reason)
                    for forbidden in ('another server', 'другого сервера', '3x-ui',
                                      'remove', 'delete', 'уберите', 'удалите', 'PRIVATE_REMNANT'):
                        self.assertNotIn(forbidden, reason)
                    self.assertEqual(before, {p: p.read_bytes() for p in root.rglob('*') if p.is_file()})
                    self.assertFalse(output.exists())

    def test_dns_diagnostics_refuse_but_cname_and_stderr_warning_are_supported(self):
        for a, aaaa in (('203.0.113.10\n;; communications error', ''),
                        ('203.0.113.10', ';; communications error: timed out'),
                        ('203.0.113.10', 'target.example.com.\n;; no servers could be reached')):
            with self.subTest(a=a, aaaa=aaaa), self.assertRaises(ValueError):
                s.dns_check(a, aaaa, '203.0.113.10')
        for failed in ('A', 'AAAA', 'none'):
            with self.subTest(failed=failed), tempfile.TemporaryDirectory() as directory:
                code = '''source "$1"
TMP=$2 DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10
dig() {
    printf ';; PRIVATE_DNS_WARNING\\n' >&2
    [[ $4 != "$FAILED" ]] || return 9
    printf 'target.example.com.\\n'
    if [[ $4 == A ]]; then printf '203.0.113.10\\n'; fi
}
FAILED=$3
dns_preflight
printf 'CONTINUED\\n'
'''
                result = subprocess.run(['bash', '-c', code, 'fixture',
                    str(ROOT/'telemt-web-manager.sh'), directory, failed], capture_output=True, timeout=5)
                self.assertEqual(result.returncode == 0, failed == 'none')
                self.assertNotIn(b'PRIVATE_DNS_WARNING', result.stdout + result.stderr)
                self.assertEqual(b'CONTINUED' in result.stdout, failed == 'none')
                self.assertTrue((Path(directory)/'dns-a.stderr').exists())
                self.assertEqual((Path(directory)/'dns-a.stderr').stat().st_mode & 0o077, 0)

if __name__ == "__main__":
    unittest.main()
