import json
import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from test_safety import ROOT, s
import shutil


class MimeTypesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'nginx'
        shutil.copytree(ROOT / 'tests/fixtures/nginx', self.root)
        self.conf = self.root / 'nginx.conf'
        self.conf.write_text(self.conf.read_text().replace('http {', 'http { include mime.fixture;'))
        self.mime = self.root / 'mime.fixture'

    def parse(self, text):
        self.mime.write_text(text)
        parser = s.Nginx(self.root)
        nodes = parser.read(self.conf)
        return parser, nodes

    def test_standard_types_and_snapshot(self):
        text = 'types { text/html html htm shtml; text/css css; application/json json; image/svg+xml svg svgz; }'
        parser, nodes = self.parse(text)
        self.assertEqual(parser.sources[self.mime.resolve()], text)
        records = s.exact(s.exact(nodes, 'http')[0].children, 'types')[0].children
        self.assertEqual(len(records), 4)
        self.assertTrue(all(n.data_record for n in records))
        s.nginx_plan(str(self.root), 'proxy.example.com', str(self.root / 'plan'))
        self.assertIn(str(self.mime), json.loads((self.root / 'plan').read_text())['snapshot'])

    def test_types_data_cannot_fabricate_directives_or_includes(self):
        text = ('types { listen 80; server 80; server_name proxy.example.com; return 301; '
                'proxy_pass fake; upstream fake; map fake; ssl_preread on; '
                'include /outside/nonexistent; text/html html; }')
        _, nodes = self.parse(text)
        self.assertFalse(any(n.data_record for n in s.walk(nodes)))
        http = s.exact(nodes, 'http')[0]
        for key in ('listen', 'server', 'server_name', 'include', 'upstream', 'map', 'return'):
            self.assertEqual(s.exact(s.exact(http.children, 'types')[0].children, key), [])
        # Compare plans and port discovery against an empty MIME table.
        a, b = self.root / 'a.json', self.root / 'b.json'
        s.nginx_plan(str(self.root), 'proxy.example.com', str(a))
        s.acme_plan(str(self.root), 'proxy.example.com', str(b), str(self.root / 'acme'))
        baseline = [json.loads(p.read_text())['edits'] for p in (a, b)]
        with contextlib.redirect_stdout(io.StringIO()) as out:
            s.port80_config(str(self.root))
        self.assertEqual(out.getvalue().strip(), '0')
        listeners = [n.args for n in s.walk(nodes) if n.args[0] == 'listen']
        _, empty = self.parse('types { }')
        self.assertEqual(listeners, [n.args for n in s.walk(empty) if n.args[0] == 'listen'])
        s.nginx_plan(str(self.root), 'proxy.example.com', str(a))
        s.acme_plan(str(self.root), 'proxy.example.com', str(b), str(self.root / 'acme'))
        self.assertEqual(baseline, [json.loads(p.read_text())['edits'] for p in (a, b)])

    def test_outside_types_and_nested_types_refused(self):
        for text in ('text/html html;', 'types { listen { listen 80; } }', 'types extra { text/html html; }'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.parse(text)

    def test_adguard_snippet_remains_ordinary_http(self):
        self.parse('types { text/html html; }')
        (self.root / 'snippets').mkdir()
        (self.root / 'conf.d').mkdir(exist_ok=True)
        (self.root / 'snippets/adguard.conf').write_text(
            'location /adguard/ { proxy_pass http://127.0.0.1:3000/; '
            'proxy_http_version 1.1; proxy_set_header Host $host; '
            'proxy_redirect off; proxy_cookie_path / /adguard/; '
            'proxy_read_timeout 90s; add_header X-Frame-Options SAMEORIGIN; access_log off; }')
        (self.root / 'conf.d/panel.conf').write_text(
            'server { listen 127.0.0.1:7443 ssl proxy_protocol; server_name panel.example.com; '
            'include snippets/adguard.conf; }')
        s.nginx_plan(str(self.root), 'proxy.example.com', str(self.root / 'plan'))

    def test_include_trust_unchanged(self):
        outside = Path(self.tmp.name) / 'external'
        outside.write_text('types { text/html html; }')
        for value in (str(outside), 'escape'):
            if value == 'escape': (self.root / value).symlink_to(outside)
            with self.subTest(value=value), self.assertRaises(ValueError):
                self.parse('include ' + value + ';')


class SemVerTests(unittest.TestCase):
    def test_syntax_and_precedence_without_version_allowlist(self):
        for value in ('3.5.7', '3.5.9', '42.7.123', '4.0.0', '4.0.0-rc.1+build.8'):
            s.semver(value)
        for a, b in (('42.0.0', '3.5.9'), ('3.5.9', '3.5.7'), ('1.0.0', '1.0.0-rc.1'),
                     ('1.0.0-rc.11', '1.0.0-rc.2'), ('1.0.0-beta', '1.0.0-1')):
            self.assertEqual(s.version_compare(a, b), 1)
            self.assertEqual(s.version_compare(b, a), -1)
        self.assertEqual(s.version_compare('4.0.0+one', '4.0.0+two'), 0)

    def test_malformed_semver_refused(self):
        for value in ('01.2.3', '1.2', 'v1.2.3', '1.2.3-01', '1.2.3 extra', '1.2.3\n', '1.2.3+'):
            with self.subTest(value=value), self.assertRaises(ValueError): s.semver(value)
