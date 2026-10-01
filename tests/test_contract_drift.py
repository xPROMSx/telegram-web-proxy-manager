"""Meaningful managed drift against actual Bash-generated TOML."""
import contextlib
import copy
import io
import json
import subprocess
import tempfile
import tomllib
import unittest
from pathlib import Path

from test_safety import ROOT, s


class ConntrackTests(unittest.TestCase):
    def setUp(self):
        self.backend = "iptables v1.8.10 (nf_tables)"
        self.diagnostic = self.backend + ": Chain 'TELEMT_NOTRACK' does not exist"
        self.record = ("WARN Failed to reconcile conntrack firewall policy "
                       "error=startup recovery failed: " + self.diagnostic)

    def classify(self, text, version="3.5.9", os="ubuntu:24.04", backend=None):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            result = s.classify(version, os, backend or self.backend, text)
        return result, out.getvalue()

    def test_ubuntu_24_and_26_exact_warning(self):
        for os in ("ubuntu:24.04", "ubuntu:26.04"):
            result, report = self.classify(self.record, os=os)
            self.assertEqual(result, 0)
            self.assertIn("known_nonfatal=1", report)

    def test_actual_tracing_prefix_help_repetition_and_old_colors(self):
        diagnostic = self.diagnostic + ".\nTry \x60iptables -h' or 'iptables --help' for more information."
        record = ("2026-10-01T00:00:00.000Z WARN telemt::conntrack_control::firewall::actor: "
                  "Failed to reconcile conntrack firewall policy generation=1 "
                  "error=startup recovery failed: " + diagnostic + "; "
                  + diagnostic.replace("iptables", "ip6tables"))
        for text in (record, "\x1b[33m" + record + "\x1b[0m", record.replace("1.8.10", "1.8.11")):
            result, report = self.classify(text)
            self.assertEqual(result, 0)
            self.assertIn("known_nonfatal=1", report)

    def test_other_version_os_backend_and_unknown_helper_refused(self):
        for changes in ({"version": "3.6.0"}, {"os": "ubuntu:22.04"},
                        {"backend": "iptables v1.8.10 (legacy)"},
                        {"backend": "nf_tables"}, {"backend": "iptables v1.8.12 (nf_tables)"}):
            with self.subTest(changes=changes):
                self.assertEqual(self.classify(self.record, **changes)[0], 1)

    def test_extra_errors_chain_context_and_severity_refused(self):
        variants = (
            self.record + "; Permission denied", self.record + "; Operation not permitted",
            self.record + "; unexpected failure", self.record + "\nadditional unexpected error",
            self.record.replace("WARN", "ERROR WARN"), self.record.replace("WARN", "FATAL WARN"),
            self.record + " panic", self.record.replace("TELEMT_NOTRACK", "OTHER_CHAIN"),
            self.record.replace("startup recovery failed:", "rollback failed:"),
            self.record.replace("Failed to reconcile conntrack firewall policy", "Other conntrack operation"),
            self.record.replace("(nf_tables):", "(legacy):"), self.record.replace("1.8.10", "1.8.12"),
            self.record + "\nERROR unrelated failure", self.record + "\nFATAL failure",
            self.record + "\npanic: failure", self.record.replace("error=", "other_error="),
        )
        for text in variants:
            with self.subTest(text=text):
                self.assertEqual(self.classify(text)[0], 1)

    def test_live_357_missing_conntrack_and_censorship_warning(self):
        unavailable = ("WARN telemt::conntrack_control: conntrack control explicitly enabled but unavailable; disabling runtime features "
                       "has_cap_net_admin=true backend_available=true conntrack_binary_available=false configured_backend=Auto")
        censorship = "WARN telemt::config::hot_reload::diff: config reload: censorship settings changed; restart required"
        result, report = self.classify(unavailable + "\n" + censorship, version="3.5.7", os="ubuntu:26.04")
        self.assertEqual(result, 1)
        self.assertIn("failures=1, warnings=1, known_nonfatal=0", report)
        self.assertEqual(self.classify(censorship, version="3.5.7")[0], 0)
        self.assertEqual(self.classify(unavailable, version="3.5.9")[0], 1)

    def test_journal_boundaries_and_redaction(self):
        for extra, expected in (("", 0), ("\nINFO additional unexpected stderr", 1),
                                ("\nPermission denied", 1)):
            # Fixture marker must never appear in the diagnostic summary.
            record = self.record + extra
            journal = json.dumps({"MESSAGE": record}) + "\n"
            journal += json.dumps({"MESSAGE": "INFO fixture-private-link"})
            with contextlib.redirect_stdout(io.StringIO()) as out:
                result = s.classify_journal("3.5.9", "ubuntu:24.04", self.backend, journal)
            self.assertEqual(result, expected)
            self.assertNotIn("fixture-private-link", out.getvalue())
        with self.assertRaises(ValueError):
            s.classify_journal("3.5.9", "ubuntu:24.04", self.backend, "invalid json")


class ManagedContractTests(unittest.TestCase):
    def setUp(self):
        self.source = subprocess.check_output(
            ["bash", "-c", 'source ./telemt-web-manager.sh; DOMAIN=proxy.example.com; '
             'PUBLIC_IP=203.0.113.10; generate_config "$(openssl rand -hex 16)"'],
            cwd=ROOT, text=True)
        self.config = tomllib.loads(self.source)

    def validate(self, config):
        return s.managed_web_contract(config, "/var/lib/telemt")

    def test_fresh_and_safe_tuning(self):
        self.assertEqual(self.validate(self.config),
                         ("proxy.example.com", "direct", "203.0.113.10"))
        config = copy.deepcopy(self.config)
        config["web"]["vhosts"][0]["profiles"][0]["max_sessions"] = 16
        config["general"]["log_level"] = "quiet"
        del config["general"]["disable_colors"]  # No automatic color migration.
        config["web"]["vhosts"][0]["decoy"].pop("index")  # Audited upstream default.
        self.validate(config)
        config["upstreams"][0] = {"type": "socks5", "address": "localhost:1080",
                                  "enabled": True, "weight": 2}
        self.assertEqual(self.validate(config)[1], "localhost:1080")

    def test_meaningful_contract_drift(self):
        cases = [
            (("general", "config_strict"), False),
            (("general", "modes", "classic"), True), (("general", "modes", "secure"), False),
            (("general", "modes", "tls"), True), (("general", "prefer_ipv6"), True),
            (("censorship", "mask"), True), (("censorship", "tls_emulation"), True),
            (("network", "ipv4"), False), (("network", "ipv6"), True),
            (("network", "prefer"), 6), (("network", "prefer"), True),
            (("network", "multipath"), True),
            (("network", "dns_overrides"), ["telegram.example.com:443:203.0.113.11"]),
            (("server", "port"), 18081), (("server", "port"), "18080"),
            (("server", "proxy_protocol"), True),
            (("server", "listen_unix_sock"), "/tmp/telemt.sock"),
            (("server", "metrics_port"), 9090), (("server", "metrics_listen"), "0.0.0.0:9090"),
            (("server", "listen_tcp"), False),
            (("server", "api", "enabled"), True), (("server", "admin_api"), {"enabled": True}),
            (("server", "conntrack_control", "mode"), "notrack"),
            (("server", "conntrack_control", "inline_conntrack_control"), False),
            (("server", "conntrack_control", "backend"), "iptables"),
            (("server", "listeners"), []),
            (("server", "listeners", 0, "ip"), "0.0.0.0"),
            (("server", "listeners", 0, "port"), 18081),
            (("server", "listeners", 0, "transport"), "mtproxy"),
            (("server", "listeners", 0, "proxy_protocol"), True),
            (("server", "listeners", 0, "web_client_ip_source"), "peer"),
            (("server", "listeners", 0, "web_trusted_proxy_cidrs"), ["0.0.0.0/0"]),
            (("server", "listeners", 0, "synlimit"), "iptables"),
            (("web", "enabled"), False), (("web", "carrier"), "websocket"),
            (("web", "carriers"), ["https", "websocket"]), (("web", "vhosts"), []),
            (("web", "vhosts", 0, "host"), "INVALID.EXAMPLE.COM"),
            (("web", "vhosts", 0, "base_path"), "custom"),
            (("web", "vhosts", 0, "public_addr"), "203.0.113.10:8443"),
            (("web", "vhosts", 0, "public_addr"), "[2001:db8::1]:443"),
            (("web", "vhosts", 0, "public_addr"), "127.0.0.1:443"),
            (("web", "vhosts", 0, "decoy", "mode"), "http_upstream"),
            (("web", "vhosts", 0, "decoy", "directory"), "/tmp/decoy"),
            (("web", "vhosts", 0, "decoy", "index"), "../private"),
            (("web", "vhosts", 0, "profiles"), []),
            (("web", "vhosts", 0, "profiles", 0, "user"), "other"),
            (("web", "vhosts", 0, "profiles", 0, "secret_mode"), "plain"),
            (("access", "users"), {"other": "fixture"}),
            (("access", "users", "web-user"), "invalid"),
            (("access", "user_enabled"), {"web-user": False}),
            (("upstreams",), []), (("upstreams", 0, "type"), "socks4"),
            (("upstreams", 0, "enabled"), False), (("upstreams", 0, "interface"), "eth0"),
            (("upstreams", 0, "bind_addresses"), ["203.0.113.11"]),
            (("upstreams", 0, "force_bind"), "eth0"), (("upstreams", 0, "scopes"), "other"),
            (("upstreams", 0, "ipv6"), True), (("upstreams", 0, "ipv4"), False),
            (("upstreams", 0, "prefer"), 6), (("upstreams", 0, "address"), "127.0.0.1:1080"),
        ]
        for path, value in cases:
            config = copy.deepcopy(self.config)
            target = config
            for part in path[:-1]:
                target = target[part]
            target[path[-1]] = value
            with self.subTest(path=path), self.assertRaises((ValueError, KeyError, TypeError)):
                self.validate(config)
        for key, value in (("username", "fixture"), ("password", "fixture"), ("address", "127.0.0.1:0")):
            config = copy.deepcopy(self.config)
            config["upstreams"][0] = {"type": "socks5", "address": "127.0.0.1:1080", key: value}
            with self.subTest(socks=key), self.assertRaises(ValueError):
                self.validate(config)
        for path in (("server", "listeners"), ("web", "vhosts"),
                     ("web", "vhosts", 0, "profiles"), ("upstreams",)):
            config = copy.deepcopy(self.config)
            target = config
            for part in path:
                target = target[part]
            target.append(copy.deepcopy(target[0]))
            with self.subTest(count=path), self.assertRaises(ValueError):
                self.validate(config)

    def test_runtime_paths_and_secret_free_diagnostics(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.toml"
            path.write_text(self.source)
            s.runtime_contract(path, "/var/lib/telemt")
            for old, new in (
                ('data_path = "/var/lib/telemt"', 'data_path = "/tmp/other"'),
                ('use_middle_proxy = false', 'use_middle_proxy = true'),
                ('destination = "stderr"', 'destination = "file"'),
                ('quota_state_path = "/var/lib/telemt/state/telemt.limit.json"',
                 'quota_state_path = "/var/lib/telemt/state"'),
                ('beobachten_file = "/var/lib/telemt/state/beobachten.txt"',
                 'beobachten_file = "/var/lib/telemt/state/../private"'),
                ('unknown_dc_file_log_enabled = false', 'unknown_dc_file_log_enabled = true'),
            ):
                drift = self.source.replace(old, new)
                if "unknown_dc_file_log_enabled = true" in drift:
                    drift = drift.replace('unknown_dc_log_path = "/var/lib/telemt/state/unknown-dc.txt"',
                                          'unknown_dc_log_path = "/tmp/unknown"')
                path.write_text(drift)
                before = path.read_bytes()
                with self.subTest(old=old), self.assertRaises(ValueError):
                    s.runtime_contract(path, "/var/lib/telemt")
                self.assertEqual(before, path.read_bytes())
            path.write_text(self.source)
            with contextlib.redirect_stdout(io.StringIO()) as out:
                s.config_info(path)
            self.assertNotIn(self.config["access"]["users"]["web-user"], out.getvalue())


class RenewalContractTests(unittest.TestCase):
    def test_unrelated_and_ambiguous_renewal_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "renewal").mkdir()
            path = root / "renewal/proxy.example.com.conf"
            valid = ("[renewalparams]\nauthenticator = webroot\nwebroot_path = /var/lib/twm,\n"
                     "[[webroot_map]]\nproxy.example.com = /var/lib/twm\n")
            path.write_text(valid)
            s.renewal_contract(root, "proxy.example.com", "/var/lib/twm")
            for text in (
                valid.replace("/var/lib/twm", "/foreign"), valid + "other.example.com = /var/lib/twm\n",
                valid + "proxy.example.com = /var/lib/twm\n", valid.replace("webroot\n", "nginx\n"),
                valid.replace("[[webroot_map]]", "[foreign]"), "privkey = /foreign/key\n" + valid,
                valid.replace("authenticator = webroot", "authenticator = standalone"),
            ):
                path.write_text(text)
                before = path.read_bytes()
                with self.subTest(text=text), self.assertRaises(ValueError):
                    s.renewal_kind(root, "proxy.example.com", "/var/lib/twm")
                self.assertEqual(before, path.read_bytes())


if __name__ == "__main__":
    unittest.main()
