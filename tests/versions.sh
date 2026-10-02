#!/usr/bin/env bash
# Compatible/incompatible synthetic official-candidate contracts; no network/services.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
# shellcheck source=telemt-web-manager.sh
source ./telemt-web-manager.sh
sandbox=$(mktemp -d)
trap 'rm -rf -- "$sandbox"' EXIT
TMP="$sandbox/tmp" DATA="$sandbox/data" BIN="$sandbox/installed" CONFIG="$sandbox/config.toml"
UNIT="$sandbox/unit" BACKUP_ROOT="$sandbox/backups"
DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10
mkdir -p "$TMP" "$DATA/state" "$DATA/public"
printf unit >"$UNIT"
printf '{"snapshot":{}}' >"$TMP/nginx-plan.json"
generate_config "$(openssl rand -hex 16)" >"$CONFIG"
make_binary() {
    python3 - "$1" "$2" "$3" <<'PY'
from pathlib import Path
import sys
path, version, behavior = sys.argv[1:]
path = Path(path)
path.write_text('#!/usr/bin/env python3\nimport sys,tomllib\nfrom pathlib import Path\n'
               + 'version=' + repr(version) + '\nbehavior=' + repr(behavior) + '\n'
               + '''if sys.argv[1:] == ['--version']:
 print('Telemt '+version);sys.exit(0)
if len(sys.argv)==3 and sys.argv[1]=='healthcheck':
 p=Path(sys.argv[2]); c=tomllib.loads(p.read_text())
 if behavior=='mutate':p.write_text('modified');sys.exit(0)
 if behavior=='incompatible':sys.exit(1)
 if behavior=='noop':sys.exit(0)
 sys.exit(1 if '__telemt_web_manager_unknown_contract' in c else 0)
sys.exit(1)
''')
path.chmod(0o755)
PY
}
make_binary "$BIN" 3.5.9 compatible
CANDIDATE="$sandbox/candidate"
make_binary "$CANDIDATE" "$SUPPORTED_TELEMT_VERSION" compatible
before=$(sha256sum "$CONFIG")
load_installation() { candidate_compatibility "$BIN" "$CONFIG"; }
download_candidate() { return 0; }
restart_service() { return 0; }
wait_ready() { [[ ${fixture_runtime_fail:-0} == 0 || $(binary_version "$BIN") == 3.5.9 ]]; }
path_health() { return 0; }
recent_logs() { return 0; }
assert_rejected() {
    local name=$1 result
    shift
    set +e
    (set -Eeuo pipefail; "$@") >"$sandbox/refusal.log" 2>&1
    result=$?
    set -e
    [[ $result != 0 ]] || die "Expected refusal: $name"
    [[ $(sha256sum "$CONFIG") == "$before" ]]
    printf 'ok - %s refused; TOML preserved\n' "$name"
}
update_manager >"$sandbox/update.log" 2>&1
[[ $(binary_version "$BIN") == "$SUPPORTED_TELEMT_VERSION" && $(sha256sum "$CONFIG") == "$before" ]]
printf 'ok - older managed install upgrades to pinned Telemt 3.5.11 (mocked lifecycle); TOML byte-identical\n'
update_manager >"$sandbox/equal.log" 2>&1
grep -q 'already up to date' "$sandbox/equal.log"
printf 'ok - equal version reports already up to date\n'
make_binary "$BIN" 3.5.11+unreviewed compatible
assert_rejected 'equal SemVer precedence but different exact supported version' update_manager
grep -q 'differs from exact supported 3.5.11; manual review required' "$sandbox/refusal.log"
[[ $(binary_version "$BIN") == 3.5.11+unreviewed ]]
make_binary "$BIN" 42.7.123 compatible
assert_rejected 'installed newer than supported target; no automatic downgrade' update_manager
grep -q 'Installed Telemt 42.7.123 is newer than supported 3.5.11; automatic downgrade refused' "$sandbox/refusal.log"
[[ $(binary_version "$BIN") == 42.7.123 ]]
make_binary "$BIN" 3.5.9 compatible
for behavior in incompatible noop mutate; do
    make_binary "$CANDIDATE" "$SUPPORTED_TELEMT_VERSION" "$behavior"
    assert_rejected "pinned candidate $behavior" update_manager
    [[ $(binary_version "$BIN") == 3.5.9 ]]
done
make_binary "$CANDIDATE" "$SUPPORTED_TELEMT_VERSION" compatible
fixture_runtime_fail=1
runtime_update() { trap cleanup EXIT; update_manager; }
assert_rejected 'incompatible activated runtime rollback' runtime_update
[[ $(binary_version "$BIN") == 3.5.9 ]]
# cleanup removed only the child temporary diagnostics directory.
mkdir -p "$TMP"
for value in '01.2.3' '1.2' '4.0.0 extra'; do
    make_binary "$CANDIDATE" "$value" compatible
    assert_rejected 'malformed binary --version' binary_version "$CANDIDATE"
done
# Check reports the audited target locally and fails mismatched installations.
# Objective health/lifecycle and certificate commands remain fixture-only.
load_installation() { return 0; }
renewal_scheduler_status() { return 0; }
systemctl() { if [[ $* == *MainPID* ]]; then printf '%s\n' "$$"; fi; }
listener_ready() { return 0; }
openssl() { return 0; }
make_binary "$BIN" "$SUPPORTED_TELEMT_VERSION" compatible
check_manager >"$sandbox/check.log" 2>&1
grep -q 'installed Telemt: 3.5.11; supported Telemt: 3.5.11' "$sandbox/check.log"
grep -q 'Check result: OK' "$sandbox/check.log"
make_binary "$BIN" 42.7.123 compatible
assert_rejected 'check newer installation requires reviewed manager/manual review' check_manager
printf 'ok - check reports installed/supported versions without a moving release query\n'
