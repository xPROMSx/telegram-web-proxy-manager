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
RENEW_HOOK="$SANDBOX/hooks/deploy/telemt-web-manager"
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
managed_permissions() { return 0; } # Fixture runs as the CI user, not root.
ensure_certificate() { return 0; }
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
python3 - "$CONFIG" "$SANDBOX/manager.log" <<'PY'
import pathlib, sys, tomllib
c = tomllib.loads(pathlib.Path(sys.argv[1]).read_text())
assert c['access']['users']['web-user'] not in pathlib.Path(sys.argv[2]).read_text()
PY
before=$(sha256sum "$CONFIG" "$BIN" "$UNIT" "$stream_file")
install_manager >"$SANDBOX/rerun.log" 2>&1
[[ $(sha256sum "$CONFIG" "$BIN" "$UNIT" "$stream_file") == "$before" ]]
printf 'ok - full fresh install and idempotent rerun in mocked filesystem\n'
