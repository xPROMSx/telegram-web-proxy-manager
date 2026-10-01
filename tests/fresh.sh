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
ensure_certificate() { return 0; }
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
    ensure_certificate() { issue_webroot_certificate; nginx_plan; }
else
    certificate_renewal_contract() { return 0; } # Minimal fixture has no Certbot assets.
fi
binary_version() { printf 3.5.9; }
fetch_release() { RELEASE=3.5.9; }
download_candidate() { CANDIDATE="$TMP/candidate"; printf '#!/bin/sh\nexit 0\n' >"$CANDIDATE"; chmod 0755 "$CANDIDATE"; }
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
candidate_healthcheck() { helper config-info "$2" >/dev/null; }
wait_ready() { return 0; }
path_health() { return 0; }
recent_logs() { return 0; }
install_manager >"$SANDBOX/manager.log" 2>&1
[[ -f $BIN && -f $UNIT && -f $CONFIG && -f $STATE/manifest.json && -f $RENEW_HOOK ]]
[[ $(stat -c %a "$CONFIG") == 640 && $(stat -c %a "$STATE/web-link.txt") == 600 ]]
cmp -s "$RENEW_HOOK" <(generate_renewal_hook)
[[ $(stat -c %a "$RENEW_HOOK") == 750 ]]
python3 - "$CONFIG" "$SANDBOX/manager.log" <<'PY'
import pathlib, sys, tomllib
c = tomllib.loads(pathlib.Path(sys.argv[1]).read_text())
assert c['access']['users']['web-user'] not in pathlib.Path(sys.argv[2]).read_text()
PY
before=$(sha256sum "$CONFIG" "$BIN" "$UNIT" "$stream_file")
install_manager >"$SANDBOX/rerun.log" 2>&1
[[ $(sha256sum "$CONFIG" "$BIN" "$UNIT" "$stream_file") == "$before" ]]
printf 'ok - full fresh install and idempotent rerun in mocked filesystem\n'
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
