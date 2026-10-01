#!/usr/bin/env bash
# Full orchestration fixture. All OS/service/account operations are mocked.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
ROOT=$PWD
# shellcheck source=telemt-web-manager.sh
source ./telemt-web-manager.sh
SANDBOX=$(mktemp -d)
trap 'rm -rf -- "$SANDBOX"' EXIT
BIN="$SANDBOX/telemt" CONFIG_DIR="$SANDBOX/etc-telemt" DATA="$SANDBOX/data"
CONFIG="$CONFIG_DIR/telemt.toml" UNIT="$SANDBOX/telemt.service" STATE="$SANDBOX/state"
BACKUP_ROOT="$SANDBOX/backups" NGINX_ROOT="$SANDBOX/nginx" TMP="$SANDBOX/tmp"
CERT_ROOT="$SANDBOX/certs"
RENEW_HOOK="$CERT_ROOT/renewal-hooks/deploy/telemt-web-manager"
DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10
mkdir "$TMP"
cp -r "${1:-$ROOT/tests/fixtures/nginx}" "$NGINX_ROOT"
mkdir -p "$NGINX_ROOT/conf.d"
stream_file="$NGINX_ROOT/stream.conf"
if [[ -f $NGINX_ROOT/stream-enabled/stream.conf ]]; then stream_file="$NGINX_ROOT/stream-enabled/stream.conf"; fi
systemctl() {
    if [[ $* == *FragmentPath* && -f $UNIT ]]; then printf '%s\n' "$UNIT"; fi
    return 0
}
ss() { return 0; }
dig() { if [[ $* == *' A '* ]]; then printf '%s\n' "$PUBLIC_IP"; fi; }
nginx_test() { return 0; }
nginx_reload() { return 0; }
nginx_runtime_identity() { return 0; }
nginx_port_owned() { return 0; }
managed_permissions() { return 0; } # Fixture runs as the CI user, not root.
certificate_stage() {
    [[ -f $SANDBOX/staged-validated && ! -e $DATA && ! -e $CONFIG_DIR && ! -e $UNIT && ! -e $STATE ]]
    printf attempted >"$SANDBOX/certificate-attempt"
}
ensure_certificate() { certificate_stage; }
validate_certificate() { return 0; } # Certificate validation has separate real-cert tests.
stat() {
    # Account/chown are mocked in this non-root orchestration fixture only.
    # tests/renewal.sh verifies real root ownership and wrong-owner refusal.
    if [[ $* == "-c %u $RENEW_HOOK" ]]; then printf '0\n'; else command stat "$@"; fi
}
if [[ -f $NGINX_ROOT/sites-enabled/80.conf ]]; then
    # Exercise ACME -> WEB replan -> manifest -> idempotent load as one install.
    # Issuance and challenge reachability are mocked; tests/acme.sh validates
    # certificates and tests/nginx.sh serves real challenge requests separately.
    ACME_ROOT="$SANDBOX/acme" CERT_ROOT="$SANDBOX/certs"
    EMAIL=operator@example.com
    validate_certificate() { return 0; }
    acme_probe() { return 0; }
    certbot() {
        mkdir -p "$CERT_ROOT/renewal"
        printf '[renewalparams]\nauthenticator = webroot\nwebroot_path = %s,\n' \
            "$ACME_ROOT" >"$CERT_ROOT/renewal/$DOMAIN.conf"
    }
    ensure_certificate() { certificate_stage; issue_webroot_certificate; nginx_plan; }
else
    certificate_renewal_contract() { return 0; } # Minimal fixture has no Certbot assets.
fi
if [[ -z ${REAL_CANDIDATE:-} ]]; then
    binary_version() { printf '%s' "${FIXTURE_VERSION:-3.5.9}"; }
fi
fetch_release() { RELEASE=${FIXTURE_VERSION:-3.5.9}; }
download_candidate() {
    CANDIDATE="$TMP/candidate"
    if [[ -n ${REAL_CANDIDATE:-} ]]; then cp -- "$REAL_CANDIDATE" "$CANDIDATE";
    else printf '#!/bin/sh\nexit 0\n' >"$CANDIDATE"; fi
    chmod 0755 "$CANDIDATE"
}
getent() { return 2; }
useradd() { return 0; }
chown() { return 0; }
install() {
    local -a args=()
    while (( $# )); do
        case $1 in -o|-g) shift 2;; *) args+=("$1"); shift;; esac
    done
    command install "${args[@]}"
}
eval "$(declare -f candidate_healthcheck | sed '1s/candidate_healthcheck/official_candidate_healthcheck/')"
candidate_healthcheck() {
    if [[ ${FIXTURE_INCOMPATIBLE:-0} == 1 ]]; then
        [[ -n ${REAL_CANDIDATE:-} ]] || return 1
        # A real strict-parser rejection on the private healthcheck copy.
        printf '\n[__telemt_web_manager_incompatible_fixture]\ninvalid = true\n' >>"$2"
    fi
    if [[ ${FIXTURE_MISSING_STATIC:-} == directory && $3 == "$TMP/compat-data" ]]; then rm -rf -- "$3/public"; fi
    if [[ ${FIXTURE_MISSING_STATIC:-} == index && $3 == "$TMP/compat-data" ]]; then rm -f -- "$3/public/index.html"; fi
    if [[ -n ${REAL_CANDIDATE:-} ]]; then official_candidate_healthcheck "$@" || return 1;
    else
    [[ -d $3/public && ! -L $3/public && -f $3/public/index.html && ! -L $3/public/index.html ]] || return 1
    ! grep -q '^__telemt_web_manager_unknown_contract = ' "$2" || return 1
    helper config-info "$2" >/dev/null || return 1
    fi
    if [[ $3 == "$TMP/compat-data" ]]; then printf ok >"$SANDBOX/staged-validated";
    else [[ -f $SANDBOX/certificate-attempt ]]; printf ok >"$SANDBOX/final-validated"; fi
}
wait_ready() { [[ -f $SANDBOX/final-validated ]]; printf ok >"$SANDBOX/readiness"; }
path_health() { printf ok >"$SANDBOX/path-health"; }
recent_logs() { printf ok >"$SANDBOX/log-health"; }
SOCKS=${FIXTURE_SOCKS:-direct}
socks_probe() { return 0; } # Config selection only; egress probes have separate coverage.
if [[ ${FIXTURE_INCOMPATIBLE:-0} == 1 || -n ${FIXTURE_MISSING_STATIC:-} ]]; then
    set +e
    (set -Eeuo pipefail; trap cleanup EXIT; install_manager) >"$SANDBOX/reject.log" 2>&1
    result=$?
    set -e
    [[ $result != 0 && ! -e $BIN && ! -e $CONFIG && ! -e $UNIT && ! -e $STATE && ! -e $DATA && ! -e $CONFIG_DIR && ! -e $RENEW_HOOK && ! -e $SANDBOX/certificate-attempt && ! -e $TMP ]]
    grep -q 'no certificate issuance attempted' "$SANDBOX/reject.log"
    printf 'ok - incompatible/missing-static fresh candidate refused before certificate/persistent installation (%s)\n' "${FIXTURE_MISSING_STATIC:-incompatible}"
    exit 0
fi
install_manager >"$SANDBOX/manager.log" 2>&1
[[ -f $BIN && -f $UNIT && -f $CONFIG && -f $STATE/manifest.json && -f $RENEW_HOOK ]]
[[ $(stat -c %a "$CONFIG") == 640 && $(stat -c %a "$STATE/web-link.txt") == 600 ]]
cmp -s "$RENEW_HOOK" <(generate_renewal_hook)
[[ $(stat -c %a "$RENEW_HOOK") == 750 ]]
[[ -f $SANDBOX/readiness && -f $SANDBOX/path-health && -f $SANDBOX/log-health ]]
python3 - "$CONFIG" "$SANDBOX/manager.log" "$TMP/fresh.toml" "$TMP/compat-data" "$DATA" "$SOCKS" <<'PY'
import pathlib, sys, tomllib
c = tomllib.loads(pathlib.Path(sys.argv[1]).read_text())
assert c['access']['users']['web-user'] not in pathlib.Path(sys.argv[2]).read_text()
final = pathlib.Path(sys.argv[1]).read_text()
assert pathlib.Path(sys.argv[3]).read_text().replace(sys.argv[4], sys.argv[5]) == final
assert sys.argv[4] not in final
assert (pathlib.Path(sys.argv[4]) / 'public/index.html').read_bytes() == (pathlib.Path(sys.argv[5]) / 'public/index.html').read_bytes()
assert c['upstreams'] == ([{'type': 'direct'}] if sys.argv[6] == 'direct' else [{'type': 'socks5', 'address': sys.argv[6]}])
PY
printf 'ok - staged/final semantics identical; no temporary path/secret leaks; final revalidation and readiness/path/log checks (%s)\n' "$SOCKS"
if [[ -n ${REAL_CANDIDATE:-} ]]; then printf 'ok - REAL official candidate validated fresh staging before certificate and final filesystem before activation\n'; fi
before=$(sha256sum "$CONFIG" "$BIN" "$UNIT" "$stream_file")
install_manager >"$SANDBOX/rerun.log" 2>&1
[[ $(sha256sum "$CONFIG" "$BIN" "$UNIT" "$stream_file") == "$before" ]]
printf 'ok - full fresh install and idempotent rerun in mocked filesystem\n'
if [[ -n ${FIXTURE_VERSION:-} ]]; then printf 'ok - compatible future fresh version %s accepted and managed load remains valid\n' "$FIXTURE_VERSION"; fi
cp "$CONFIG" "$SANDBOX/original.toml"
sed 's/secret_mode = "dd"/secret_mode = "plain"/' "$CONFIG" >"$SANDBOX/drift"
cp "$SANDBOX/drift" "$CONFIG"
drift_hash=$(sha256sum "$CONFIG")
set +e
(set -Eeuo pipefail; load_installation) >"$SANDBOX/drift.log" 2>&1
result=$?
set -e
[[ $result != 0 && $(sha256sum "$CONFIG") == "$drift_hash" ]]
cp "$SANDBOX/original.toml" "$CONFIG"
printf 'ok - installation load refuses meaningful TOML drift without rewriting it\n'
printf '/usr/bin/true\n' >>"$RENEW_HOOK"
before=$(sha256sum "$CONFIG" "$BIN" "$UNIT" "$RENEW_HOOK" "$STATE/manifest.json" "$stream_file")
for action in check_manager update_manager repair_manager; do
    set +e
    (set -Eeuo pipefail; "$action") >"$SANDBOX/hook-$action.log" 2>&1
    result=$?
    set -e
    [[ $result != 0 ]]
    grep -q 'Managed Certbot deploy hook changed' "$SANDBOX/hook-$action.log"
    [[ $(sha256sum "$CONFIG" "$BIN" "$UNIT" "$RENEW_HOOK" "$STATE/manifest.json" "$stream_file") == "$before" ]]
done
printf 'ok - real installation load refuses altered deploy hook before check/update/repair without mutation\n'
