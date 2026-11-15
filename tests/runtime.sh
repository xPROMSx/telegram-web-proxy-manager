#!/usr/bin/env bash
# Real pinned binary, Linux helpers/listener/HTTP/logs. No systemd or Certbot.
# All firewall commands run only in a new network namespace.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
ROOT=$PWD
# shellcheck source=telemt-web-manager.sh
source ./telemt-web-manager.sh

if [[ ${1:-} == --inside ]]; then
    fixture=$2 candidate=$3 host_namespace=$4
    current_namespace=$(readlink /proc/self/ns/net)
    [[ $EUID == 0 && $host_namespace =~ ^net:\[[0-9]+\]$ && $current_namespace != "$host_namespace" ]] ||
        die 'Runtime smoke refuses the parent/host network namespace'
    printf 'Real isolated runtime namespace: %s (parent %s)\n' "$current_namespace" "$host_namespace"
    ip link set lo up
    for tool in nft iptables ip6tables conntrack; do command -v "$tool"; "$tool" --version; done
    python3 - <<'PY'
from pathlib import Path
caps = next(line.split()[1] for line in Path('/proc/self/status').read_text().splitlines() if line.startswith('CapEff:'))
assert int(caps, 16) & (1 << 12), 'real CAP_NET_ADMIN required'
print('Real CAP_NET_ADMIN context verified')
PY
    [[ $(binary_version "$candidate") == "$SUPPORTED_TELEMT_VERSION" ]]
    printf 'Real runtime Telemt version: %s\n' "$SUPPORTED_TELEMT_VERSION"
    pid=''
    origin_pid=''
    # Invoked by EXIT trap, including failed readiness/classification/shutdown.
    # shellcheck disable=SC2317
    stop_on_failure() {
        if [[ -n $origin_pid ]]; then kill -TERM "$origin_pid" 2>/dev/null || true; wait "$origin_pid" 2>/dev/null || true; fi
        if [[ -n $pid ]] && kill -0 "$pid" 2>/dev/null; then
            kill -TERM "$pid" 2>/dev/null || true
            for ((i=0; i<100; i++)); do
                if ! kill -0 "$pid" 2>/dev/null; then break; fi
                sleep 0.1
            done
            kill -KILL "$pid" 2>/dev/null || true
            wait "$pid" 2>/dev/null || true
        fi
    }
    trap stop_on_failure EXIT
    owned_pattern='telemt_conntrack(_a|_b)?|TELEMT_NOTRACK|TELEMT_NT_[AB]'
    # Pinned upstream contract only; production WARN severity stays generic.
    failure_patterns=(-e 'Failed to reconcile conntrack firewall policy'
        -e 'Initial conntrack firewall reconciliation failed'
        -e 'background retries remain active'
        -e 'Failed to clear conntrack firewall policy during shutdown'
        -e 'Conntrack firewall cleanup did not complete successfully')
    nft list ruleset >"$fixture/nft-before"
    iptables-save >"$fixture/iptables-before"
    ip6tables-save >"$fixture/ip6tables-before"
    if grep -Eiq "$owned_pattern" "$fixture/nft-before" "$fixture/iptables-before" "$fixture/ip6tables-before"; then
        die 'Fresh namespace unexpectedly contains Telemt-owned firewall state'
    fi
    printf 'ok - REAL pre-start nft/IPv4/IPv6 inspection: Telemt-owned chains absent (old recovery trigger)\n'
    # Upstream's "stderr" tracing layer uses the fmt default stdout writer;
    # the MAESTRO startup banner uses stderr. Capture both as journald does.
    # Do not inherit the Cloud executor's RUST_LOG=...error filter.
    python3 - "$ROOT" "$fixture" <<'PY_ORIGIN'
import importlib.util,sys
from pathlib import Path
spec=importlib.util.spec_from_file_location('runtime_origin',Path(sys.argv[1])/'lib/safety.py')
s=importlib.util.module_from_spec(spec);sys.modules[spec.name]=s;spec.loader.exec_module(s)
p=Path(sys.argv[2])
(p/'origin.conf').write_text('worker_processes 1; pid '+str(p/'origin.pid')+'; error_log '+str(p/'origin.log')+' crit; events {} http {'+s.render_site_server(p/'site')+'}')
PY_ORIGIN
    nginx -p "$fixture/" -c "$fixture/origin.conf" -g 'daemon off; master_process off;' >/dev/null 2>&1 &
    origin_pid=$!
    env -u RUST_LOG "$candidate" "$fixture/runtime.toml" >"$fixture/stderr" 2>&1 &
    pid=$!
    printf 'Real Telemt process started: pid=%s\n' "$pid"
    python3 - "$pid" <<'PY'
from pathlib import Path
import sys
caps = next(line.split()[1] for line in Path('/proc/' + sys.argv[1] + '/status').read_text().splitlines() if line.startswith('CapEff:'))
assert int(caps, 16) & (1 << 12), 'actual Telemt process needs CAP_NET_ADMIN'
print('Actual Telemt process CAP_NET_ADMIN verified')
PY
    ready=0
    for ((i=0; i<900; i++)); do
        kill -0 "$pid" || die 'Real Telemt exited before readiness'
        if ss -H -ltnp 'sport = :18080' | grep -Fq "pid=$pid," &&
           curl --noproxy '*' -fsS --max-time 2 -H 'Host: proxy.example.com' \
                http://127.0.0.1:18080/ -o "$fixture/http-body"; then ready=1; break; fi
        sleep 0.1
    done
    (( ready )) || die 'Real listener/HTTP did not become ready'
    cmp -s "$fixture/http-body" "$fixture/site/index.html"
    printf 'ok - REAL pinned listener owned by Telemt PID; real HTTP 200 serves generated managed index\n'
    # Old actor retries after 1s, 2s, 4s, then backs off to a 30s cap.
    # HTTP readiness alone could mask permanently failed reconciliation.
    dwell_started=$(python3 -c 'import time; print(time.monotonic_ns())')
    sleep 10
    kill -0 "$pid" || die 'Real Telemt died after initial HTTP'
    ss -H -ltnp 'sport = :18080' | grep -Fq "pid=$pid,"
    curl --noproxy '*' -fsS --max-time 2 -H 'Host: proxy.example.com' \
        http://127.0.0.1:18080/ -o "$fixture/http-body"
    cmp -s "$fixture/http-body" "$fixture/site/index.html"
    python3 - "$dwell_started" <<'PY'
import sys, time
elapsed = time.monotonic_ns() - int(sys.argv[1])
assert elapsed >= 10_000_000_000, 'minimum ten-second post-readiness dwell required'
print(f'ok - REAL post-readiness runtime dwell {elapsed / 1e9:.3f}s >= 10s; PID/listener/HTTP index remain healthy')
PY
    # Reuse the Update acceptance protocol probe against this Fresh baseline.
    # Public cover HTTP alone does not establish the authenticated WEB contract.
    python3 - "$ROOT" "$fixture/runtime.toml" <<'PY'
import importlib.util, sys
try:
    spec = importlib.util.spec_from_file_location('fresh_web_runtime',sys.argv[1]+'/lib/safety.py')
    s = importlib.util.module_from_spec(spec); sys.modules[spec.name] = s; spec.loader.exec_module(s)
    s.UpdateWEBProbe(s.read_config(sys.argv[2])).run(full=False)
except Exception:
    raise SystemExit('REAL Fresh WEB protocol probe failed; private configuration withheld') from None
print('ok - REAL authenticated WEB bootstrap/session/Hello/uplink replay/close: PASS')
PY
    python3 "$ROOT/tests/nginx_keepalive_fixture.py" "$fixture/runtime.toml" "$fixture/site"
    # Site files never rotate. Ordinary HTTP and authenticated WEB probes above
    # must leave all eleven files unchanged.
    [[ $(helper site-identity "$fixture/site") == "$(cat "$fixture/site.sha256")" ]]
    if grep -Fq "${failure_patterns[@]}" "$fixture/stderr"; then
        die 'Pinned runtime has conntrack reconciliation/retry failure'
    fi
    printf 'ok - actual pinned startup/retry output: NO conntrack reconciliation failure/retry fragments\n'
    helper classify <"$fixture/stderr" >"$fixture/startup-summary"
    cat "$fixture/startup-summary"
    grep -Eq 'errors=0, warnings=[1-9][0-9]*' "$fixture/startup-summary"
    python3 - "$fixture/stderr" <<'PY'
from pathlib import Path
import sys
text = Path(sys.argv[1]).read_text()
# Print only these verified, secret-free fragments of actual captured output.
for fragment in ('config reload: censorship settings changed; restart required',):
    if fragment in text: print('Observed actual startup WARN fragment: ' + fragment)
PY
    printf 'ok - REAL startup stderr consumed by production classifier; observed WARNs permit healthy runtime\n'
    for fatal in 'ERROR telemt::fixture: WARN injected failure' 'FATAL telemt::fixture: WARN injected failure' "thread 'main' panicked at src/fixture.rs:1: WARN"; do
        cp "$fixture/stderr" "$fixture/negative"
        printf '\n%s\n' "$fatal" >>"$fixture/negative"
        if helper classify <"$fixture/negative" >"$fixture/negative-summary"; then die 'Fatal injection accepted'; fi
        grep -Eq 'errors=1, warnings=[1-9][0-9]*' "$fixture/negative-summary"
    done
    printf 'ok - production classifier rejects genuine ERROR/FATAL/Rust panic added to real captured stderr\n'
    kill -TERM "$pid"
    for ((i=0; i<1800; i++)); do
        if ! kill -0 "$pid" 2>/dev/null; then break; fi
        sleep 0.1
    done
    if kill -0 "$pid" 2>/dev/null; then die 'Real Telemt graceful shutdown timed out'; fi
    wait "$pid"
    pid=''
    helper classify <"$fixture/stderr"
    if grep -Fq "${failure_patterns[@]}" "$fixture/stderr"; then
        die 'Pinned runtime has conntrack startup/retry/shutdown failure'
    fi
    printf 'ok - actual completed pinned log: NO conntrack reconciliation/retry/shutdown failure fragments\n'
    assert_link_logging_contract() {
        if grep -Fq 'tg://webproxy' "$fixture/stderr"; then
            die 'Fresh configuration leaked a WEB link into captured service output'
        fi
        # Test fixture only: production never rewrites an installed TOML.
        python3 - "$fixture/runtime.toml" "$fixture/legacy.toml" <<'PY_LINKS'
from pathlib import Path
import sys
source = Path(sys.argv[1]).read_bytes()
block = b'[general.links]\nshow = []\n'
assert source.count(block) == 1
Path(sys.argv[2]).write_bytes(source.replace(block, b''))
PY_LINKS
        helper runtime-contract "$fixture/legacy.toml" "$fixture/data"
        env -u RUST_LOG "$candidate" "$fixture/legacy.toml" >"$fixture/legacy-output" 2>&1 &
        pid=$!
        ready=0
        for ((i=0; i<900; i++)); do
            kill -0 "$pid" || die 'Legacy configuration exited before readiness'
            if ss -H -ltnp 'sport = :18080' | grep -Fq "pid=$pid," &&
               curl --noproxy '*' -fsS --max-time 2 -H 'Host: proxy.example.com' \
                    http://127.0.0.1:18080/ -o "$fixture/legacy-body"; then ready=1; break; fi
            sleep 0.1
        done
        (( ready )) || die 'Legacy configuration did not become ready'
        cmp -s "$fixture/legacy-body" "$fixture/site/index.html"
        kill -TERM "$pid"
        for ((i=0; i<1800; i++)); do
            if ! kill -0 "$pid" 2>/dev/null; then break; fi
            sleep 0.1
        done
        if kill -0 "$pid" 2>/dev/null; then die 'Legacy configuration shutdown timed out'; fi
        wait "$pid"
        pid=''
        grep -Fq 'tg://webproxy' "$fixture/legacy-output" || die 'Legacy link logging positive control failed'
        printf 'ok - REAL Telemt 3.5.16: fresh links.show=[] suppresses WEB links; legacy configuration starts and logs links (private output withheld)\n'
    }
    assert_link_logging_contract
    nft list ruleset >"$fixture/nft-after"
    iptables-save >"$fixture/iptables-after"
    ip6tables-save >"$fixture/ip6tables-after"
    if grep -Eiq "$owned_pattern" \
        "$fixture/nft-after" "$fixture/iptables-after" "$fixture/ip6tables-after"; then
        die 'Unexpected Telemt-owned firewall state after shutdown'
    fi
    printf 'ok - real graceful shutdown and namespace nft/IPv4/IPv6 inspection: no Telemt-owned firewall state\n'
    exit 0
fi

namespace_args=(--net)
if [[ ${1:-} == --user-namespace ]]; then namespace_args=(--user --map-root-user --net);
elif [[ $# != 0 || $EUID != 0 ]]; then die 'Use root on the disposable runner, or --user-namespace where supported'; fi
TMP=$(mktemp -d)
runtime_cleanup() {
    local result=$?
    if (( result )); then printf 'Runtime failed; private evidence retained at %s (do not publish raw logs)\n' "$TMP" >&2;
    else rm -rf -- "$TMP"; fi
    exit "$result"
}
trap runtime_cleanup EXIT
DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10 DATA="$TMP/data"
install -d -m 0750 "$DATA" "$DATA/state" "$DATA/public"
SITE_ROOT="$TMP/site"
SITE_DIGEST=$(helper site-generate "$SITE_ROOT")
printf '%s\n' "$SITE_DIGEST" >"$TMP/site.sha256"
secret=$(openssl rand -hex 16)
generate_config "$secret" >"$TMP/runtime.toml"
unset secret
download_candidate
candidate_compatibility "$CANDIDATE" "$TMP/runtime.toml"
python3 - "$TMP/runtime.toml" <<'PY'
from pathlib import Path
import sys, tomllib
c = tomllib.loads(Path(sys.argv[1]).read_text())
assert c['server']['conntrack_control'] == {'inline_conntrack_control': True, 'mode': 'tracked'}
assert c['server']['listeners'][0]['ip'] == '127.0.0.1'
print('Production-generated strict tracked-mode TOML and original HTTP site verified')
PY
host_namespace=$(readlink /proc/self/ns/net)
unshare "${namespace_args[@]}" bash "$ROOT/tests/runtime.sh" --inside "$TMP" "$CANDIDATE" "$host_namespace"
if [[ -n ${TELEMT_TEST_EVIDENCE_DIR:-} ]]; then
    printf '%s\n' "$SUPPORTED_TELEMT_VERSION" >"$TELEMT_TEST_EVIDENCE_DIR/runtime.version"
    chmod 0644 "$TELEMT_TEST_EVIDENCE_DIR/runtime.version"
fi
printf 'ok - real Linux runtime smoke completed for production-pinned Telemt %s; service lifecycle not tested\n' "$SUPPORTED_TELEMT_VERSION"
