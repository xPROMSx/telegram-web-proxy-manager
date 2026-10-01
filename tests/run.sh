#!/usr/bin/env bash
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
python3 -m unittest discover -s tests -p 'test_*.py' -v
ROOT=$PWD
SANDBOX=$(mktemp -d)
trap 'rm -rf -- "$SANDBOX"' EXIT
export ROOT SANDBOX

run_case() {
    local name=$1
    shift
    if (set -Eeuo pipefail; "$@"); then
        printf 'ok - %s\n' "$name"
    else
        printf 'FAIL - %s\n' "$name" >&2
        exit 1
    fi
}

# Every case executes a new shell: no conditional-function errexit masking.
# SC2016: this literal is executed by the child Bash, which must expand its variables.
# shellcheck disable=SC2016
run_case 'direct and SOCKS config; generated secret never logged' bash -c '
source "$ROOT/telemt-web-manager.sh"
DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10
token=$(openssl rand -hex 16)
generate_config "$token" >"$SANDBOX/direct.toml"
helper config-info "$SANDBOX/direct.toml" >"$SANDBOX/info"
grep -qx direct "$SANDBOX/info"
! grep -Fq "$token" "$SANDBOX/info"
SOCKS=127.0.0.1:1080
generate_config "$token" >"$SANDBOX/socks.toml"
helper config-info "$SANDBOX/socks.toml" >"$SANDBOX/info"
grep -qx 127.0.0.1:1080 "$SANDBOX/info"
! grep -Fq "$token" "$SANDBOX/info"
'

# SC2016: this literal is executed by the child Bash, which must expand its variables.
# shellcheck disable=SC2016
run_case 'SOCKS Telegram success and failure; direct skips probe' bash -c '
source "$ROOT/telemt-web-manager.sh"
curl() { [[ $* == *https://api.telegram.org/* && $* == *socks5h://127.0.0.1:1080* ]]; }
SOCKS=127.0.0.1:1080
socks_probe
curl() { return 1; }
! socks_probe
SOCKS=
socks_probe
'

# SC2016: this literal is executed by the child Bash, which must expand its variables.
# shellcheck disable=SC2016
run_case 'already supported does not touch binary or config' bash -c '
source "$ROOT/telemt-web-manager.sh"
RELEASE=$SUPPORTED_TELEMT_VERSION
candidate_healthcheck() { exit 55; }
backup_begin() { exit 56; }
update_transaction "$SUPPORTED_TELEMT_VERSION"
'

# SC2016: this literal is executed by the child Bash, which must expand its variables.
# shellcheck disable=SC2016
run_case 'candidate rejection leaves installed bytes untouched' bash -c '
source "$ROOT/telemt-web-manager.sh"
BIN="$SANDBOX/reject-bin" CONFIG="$SANDBOX/reject-config"
printf old >"$BIN"; printf original >"$CONFIG"
RELEASE=$SUPPORTED_TELEMT_VERSION CANDIDATE="$SANDBOX/candidate"
candidate_healthcheck() { return 1; }
candidate_compatibility() { candidate_healthcheck "$@"; }
set +e
(update_transaction 3.5.9) >"$SANDBOX/rejection.log" 2>&1
rc=$?
set -e
[[ $rc != 0 && $(cat "$BIN") == old && $(cat "$CONFIG") == original ]]
'

# SC2016: this literal is executed by the child Bash.
# shellcheck disable=SC2016
run_case 'concurrent config edit during candidate validation refuses before binary replacement' bash -c '
source "$ROOT/telemt-web-manager.sh"
BIN="$SANDBOX/concurrent-bin" CONFIG="$SANDBOX/concurrent-config"
printf old >"$BIN"; printf original >"$CONFIG"
RELEASE=$SUPPORTED_TELEMT_VERSION CANDIDATE="$SANDBOX/candidate"
candidate_healthcheck() { printf edited >"$CONFIG"; }
candidate_compatibility() { candidate_healthcheck "$@"; }
backup_begin() { exit 56; }
set +e
(update_transaction 3.5.9) >"$SANDBOX/concurrent.log" 2>&1
rc=$?
set -e
[[ $rc != 0 && $rc != 56 && $(cat "$BIN") == old && $(cat "$CONFIG") == edited ]]
'

# SC2016: child shell expands paths.
# shellcheck disable=SC2016
run_case 'older compatible install reaches the pinned candidate download' bash -c '
source "$ROOT/telemt-web-manager.sh"
load_installation() { return 0; }
binary_version() { printf 3.5.9; }
path_health() { return 0; }
download_candidate() { [[ $RELEASE == "$SUPPORTED_TELEMT_VERSION" ]] || exit 58; exit 57; }
set +e
(update_manager) >"$SANDBOX/future.log" 2>&1
rc=$?
set -e
[[ $rc == 57 ]]
'

# SC2016: this literal is executed by the child Bash, which must expand its variables.
# shellcheck disable=SC2016
run_case 'readiness handles 18-second cold start and bounded timeout' bash -c '
source "$ROOT/telemt-web-manager.sh"
tick=0
now() { printf "%s\n" "$tick"; }
pause() { tick=$((tick+1)); }
systemctl() { printf active; }
service_active() { return 0; }
listener_ready() { (( tick >= 18 )); }
wait_ready 90
[[ $tick == 18 ]]
tick=0
listener_ready() { return 1; }
! wait_ready 3
[[ $tick == 3 ]]
systemctl() { printf failed; }
! wait_ready 90
'

# SC2016: this literal is executed by the child Bash, which must expand its variables.
# shellcheck disable=SC2016
run_case 'failed startup rolls back old binary and restarts it' bash -c '
source "$ROOT/telemt-web-manager.sh"
BIN="$SANDBOX/rollback-bin" CONFIG="$SANDBOX/rollback-config" UNIT="$SANDBOX/unit"
BACKUP_ROOT="$SANDBOX/backups" TMP="$SANDBOX/update-tmp"
mkdir "$TMP"
printf old >"$BIN"; printf original >"$CONFIG"; printf unit >"$UNIT"
printf "{\"snapshot\":{}}" >"$TMP/nginx-plan.json"
CANDIDATE="$SANDBOX/new-bin"; printf new >"$CANDIDATE"
RELEASE=$SUPPORTED_TELEMT_VERSION
candidate_healthcheck() { return 0; }
candidate_compatibility() { candidate_healthcheck "$@"; }
restart_service() { printf "%s\n" "$(cat "$BIN")" >>"$SANDBOX/restarts"; }
wait_ready() { [[ $(cat "$BIN") == old ]]; }
set +e
(trap cleanup EXIT; update_transaction 3.5.9) >"$SANDBOX/rollback.log" 2>&1
rc=$?
set -e
[[ $rc != 0 && $(cat "$BIN") == old && $(cat "$CONFIG") == original ]]
[[ $(tail -n1 "$SANDBOX/restarts") == old ]]
'

# SC2016: this literal is executed by the child Bash, which must expand its variables.
# shellcheck disable=SC2016
run_case 'nginx validation failure restores all mutations' bash -c '
source "$ROOT/telemt-web-manager.sh"
NGINX_ROOT="$SANDBOX/nginx"
cp -r "$ROOT/tests/fixtures/nginx" "$NGINX_ROOT"; mkdir "$NGINX_ROOT/conf.d"
TMP="$SANDBOX/nginx-tmp"; mkdir "$TMP"
DOMAIN=proxy.example.com BACKUP_ROOT="$SANDBOX/nginx-backups"
nginx_plan
before=$(sha256sum "$NGINX_ROOT/stream.conf")
nginx_test() { [[ ! -e $NGINX_ROOT/conf.d/telemt-web-manager.conf ]]; }
nginx_reload() { return 0; }
systemctl() { return 0; }
set +e
(trap cleanup EXIT; backup_begin; ARMED=1 INSTALLING=1; apply_nginx) >"$SANDBOX/nginx.log" 2>&1
rc=$?
set -e
[[ $rc != 0 && $(sha256sum "$NGINX_ROOT/stream.conf") == "$before" ]]
[[ ! -e $NGINX_ROOT/conf.d/telemt-web-manager.conf ]]
'

# SC2016: this literal is executed by the child Bash, which must expand its variables.
# shellcheck disable=SC2016
run_case 'DNS mismatch refuses before mutation' bash -c '
source "$ROOT/telemt-web-manager.sh"
TMP="$SANDBOX/dns"; mkdir "$TMP"
DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10
dig() { if [[ $* == *" A "* ]]; then printf 203.0.113.11; fi; }
set +e
(dns_preflight; touch "$SANDBOX/destructive") >"$SANDBOX/dns.log" 2>&1
rc=$?
set -e
[[ $rc != 0 && ! -e $SANDBOX/destructive ]]
'

# SC2016: this literal is executed by the child Bash, which must expand its variables.
# shellcheck disable=SC2016
run_case 'concurrent mutation is refused' bash -c '
source "$ROOT/telemt-web-manager.sh"
LOCK="$SANDBOX/lock"
take_lock
set +e
bash -c '\''source "$ROOT/telemt-web-manager.sh"; LOCK="$SANDBOX/lock"; take_lock'\'' >"$SANDBOX/lock.log" 2>&1
rc=$?
set -e
[[ $rc != 0 ]]
'

# SC2016: this literal is executed by the child Bash, which must expand its variables.
# shellcheck disable=SC2016
run_case 'non-interactive menu fails promptly' bash -c '
if timeout 5 bash "$ROOT/telemt-web-manager.sh" </dev/null >"$SANDBOX/menu.log" 2>&1; then exit 1; fi
grep -q "No interactive terminal" "$SANDBOX/menu.log"
'
