import contextlib
import importlib.util
import io
import json
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


if __name__ == "__main__":
    unittest.main()
