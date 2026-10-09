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


class JournalSeverityTests(unittest.TestCase):
    """Historical 3.5.10 live WARNs; not healthy pinned-runtime expectations."""
    def setUp(self):
        self.journal = (ROOT / 'tests/fixtures/journal/telemt-3.5.10-live-warnings.jsonl').read_text()
        self.records = [json.loads(line)['MESSAGE'] for line in self.journal.splitlines()]
        self.raw = "\n".join(self.records)

    def result(self, text, journal=False):
        with contextlib.redirect_stdout(io.StringIO()) as out:
            result = (s.classify_journal if journal else s.classify)(text)
        return result, out.getvalue()

    def test_exact_seven_live_warnings_raw_and_journal(self):
        self.assertEqual(len(self.records), 7)
        for text, journal in ((self.raw, False), (self.journal, True)):
            result, report = self.result(text, journal)
            self.assertEqual(result, 0)
            self.assertIn('errors=0, warnings=7', report)
            self.assertNotIn('known_nonfatal', report)
        # Historical version==3.5.9/string rules rejected these live 3.5.10
        # WARNs while WEB/path health was OK. The policy now has no version input.

    def test_payload_keywords_never_change_warn_or_info_severity(self):
        for level in ('TRACE', 'DEBUG', 'INFO', 'WARN'):
            for payload in ('conntrack', 'Permission denied', 'Operation not permitted',
                            'error=startup recovery failed', 'ERROR FATAL panic',
                            'tg://fixture-private-secret-link'):
                with self.subTest(level=level, payload=payload):
                    result, report = self.result(level + ' telemt::fixture: ' + payload)
                    self.assertEqual(result, 0)
                    self.assertIn('errors=0, warnings=' + str(int(level == 'WARN')), report)
                    self.assertNotIn(payload, report)

    def test_real_fatal_levels_and_rust_panic_with_warn_payload(self):
        for fatal in ('ERROR telemt::fixture: WARN error=failed',
                      'FATAL telemt::fixture: WARN', 'panic: WARN',
                      "thread 'main' panicked at src/main.rs:1: WARN",
                      "thread 'tokio-runtime-worker' (123) panicked at src/main.rs:1: WARN",
                      'fatal runtime error: failed to initiate panic'):
            for journal in (False, True):
                with self.subTest(fatal=fatal, journal=journal):
                    text = self.journal + json.dumps({'MESSAGE': fatal}) if journal else self.raw + '\n' + fatal
                    result, report = self.result(text, journal)
                    self.assertEqual(result, 1)
                    self.assertIn('errors=1, warnings=7', report)

    def test_multiline_boundaries_cannot_hide_fatal_records(self):
        for fatal in ('ERROR telemt: WARN', 'FATAL telemt: WARN', "thread 'main' panicked at src/x.rs:1"):
            record = 'WARN telemt: harmless continuation\nINFO diagnostic\n' + fatal
            result, report = self.result(json.dumps({'MESSAGE': record}), True)
            self.assertEqual(result, 1)
            self.assertIn('errors=1, warnings=1', report)
        result, report = self.result(json.dumps({'MESSAGE': 'WARN error=failed\nPermission denied'}), True)
        self.assertEqual(result, 0)
        self.assertIn('warnings=1', report)

    def test_ansi_sgr_colors_preserve_structural_severity(self):
        for level, expected in (('WARN', 0), ('ERROR', 1), ('FATAL', 1)):
            result, _ = self.result('2026-10-01T00:00:00.000+03:00 \x1b[1;33m' + level + '\x1b[0m telemt: WARN error=failed')
            self.assertEqual(result, expected)

    def test_malformed_transport_and_unknown_prefix_fail_closed(self):
        for text in ('invalid json', '[]', '{}', '{"MESSAGE":[87,65]}',
                     '{"MESSAGE":"WARN x","extra":NaN}',
                     '{"MESSAGE":"WARN x","extra":Infinity}',
                     '{"MESSAGE":"WARN x","MESSAGE":"INFO x"}',
                     '{"MESSAGE":"unframed error"}', '{"MESSAGE":"WARN \u001b[2Jx"}',
                     '{"MESSAGE":"WARN \u0000x"}'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                self.result(text, True)
        for text in ('unframed text', '\x1b[2JWARN x', '??? ERROR x'):
            with self.subTest(text=text), self.assertRaises(ValueError): self.result(text)

    def test_systemd_manager_records_require_trusted_identity_metadata(self):
        unit = {'MESSAGE': 'Started telemt.service.', '_PID': '1', '_COMM': 'systemd'}
        self.assertEqual(self.result(json.dumps(unit), True)[0], 0)
        unit['_PID'] = '54321'
        with self.assertRaises(ValueError): self.result(json.dumps(unit), True)

    def test_private_payload_is_never_printed_and_empty_logs_are_valid(self):
        text = json.dumps({'MESSAGE': 'ERROR telemt: tg://fixture-private-secret-link'})
        result, report = self.result(text, True)
        self.assertEqual(result, 1)
        self.assertNotIn('fixture-private', report)
        self.assertEqual(self.result('', True), (0, 'logs: errors=0, warnings=0\n'))

    def test_actual_startup_banner_and_both_tracing_streams(self):
        # The upstream stderr destination uses stdout for tracing, stderr for
        # the unlevelled MAESTRO banner. Journald captures both streams.
        banner = 'MAESTRO: Telemt MTProxy v3.5.10\nMAESTRO: tg://fixture-private-link\n'
        result, report = self.result(banner + self.raw)
        self.assertEqual((result, report), (0, 'logs: errors=0, warnings=7\n'))
        self.assertNotIn('fixture-private', report)
        result, report = self.result(banner + self.raw + '\nERROR telemt: WARN')
        self.assertEqual((result, report), (1, 'logs: errors=1, warnings=7\n'))
        for control in ('\x00', '\x1b[2J', '\x07', '\x9b2J'):
            with self.assertRaises(ValueError):
                self.result(json.dumps({'MESSAGE': 'WARN x' + control}), True)


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


class FreshHTTPSBudgetTests(unittest.TestCase):
    def run_budget(self, mode):
        # Actual http_ok()/wait_https_ready(); only curl transport and clock fake.
        script = r'''source "$1/telemt-web-manager.sh"
DOMAIN=proxy.example.com
# File descriptor avoids subprocess variable state disappearing in http_ok().
exec 3>"$2"
curl() {
    local previous='' limit=0 arg
    for arg in "$@"; do
        [[ $arg != -k && $arg != --insecure ]] || return 99
        if [[ $previous == --max-time ]]; then limit=$arg; fi
        previous=$arg
    done
    [[ $limit -gt 0 && $limit -le 5 ]] || return 98
    printf '%s\n' "$limit" >&3
    if [[ $mode == immediate ]]; then printf 200; return 0; fi
    return 28
}
# SECONDS is changed by the parent http_ok wrapper, not the curl subshell.
eval "$(declare -f http_ok | sed '1s/http_ok/production_http_ok/')"
mode=$3
http_ok() {
    local previous='' limit=0 arg
    for arg in "$@"; do
        if [[ $previous == --max-time ]]; then limit=$arg; fi
        previous=$arg
    done
    if [[ $mode == immediate ]]; then production_http_ok "$@"; return "$?"; fi
    SECONDS=$((SECONDS+limit))
    if [[ $mode == public-fail && $* == *--resolve* ]]; then printf '%s\n' "$limit" >&3; return 0; fi
    production_http_ok "$@"
}
sleep() { [[ $1 == 1 ]]; SECONDS=$((SECONDS+1)); }
SECONDS=0
result=0
wait_https_ready || result=$?
printf '%s %s\n' "$result" "$SECONDS"
'''
        with tempfile.TemporaryDirectory() as directory:
            calls = Path(directory)/'calls'
            result = subprocess.run(['bash', '-c', script, 'fixture', str(ROOT), str(calls), mode],
                                    capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 0, result.stderr)
            return tuple(map(int, result.stdout.split())), list(map(int, calls.read_text().split()))

    def test_immediate_readiness_needs_two_requests_and_no_pause(self):
        state, limits = self.run_budget('immediate')
        self.assertEqual(state, (0, 0))
        self.assertEqual(limits, [5, 5])

    def test_timeouts_do_not_extend_the_overall_deadline(self):
        state, limits = self.run_budget('timeout')
        self.assertEqual(state, (1, 29))
        self.assertEqual(limits, [5, 5, 5, 5, 5])

    def test_public_failure_recomputes_remaining_request_budget(self):
        state, limits = self.run_budget('public-fail')
        self.assertEqual(state, (1, 29))
        self.assertEqual(limits, [5, 5, 5, 5, 5, 2])


    def test_existing_path_check_keeps_fail_fast_https_contract(self):
        script = r'''source "$1/telemt-web-manager.sh"
DOMAIN=proxy.example.com
nginx_test() { return 0; }
service_active() { return 0; }
listener_ready() { return 0; }
process_identity() { return 0; }
http_ok() { [[ $* != *https://* ]]; }
wait_https_ready() { printf UNEXPECTED_RETRY; return 0; }
socks_probe() { printf UNEXPECTED_SOCKS; return 0; }
if path_health; then exit 99; fi
'''
        result = subprocess.run(['bash', '-c', script, 'fixture', str(ROOT)],
                                capture_output=True, text=True, timeout=5)
        self.assertEqual((result.returncode, result.stdout, result.stderr), (0, '', ''))


if __name__ == "__main__":
    unittest.main()
