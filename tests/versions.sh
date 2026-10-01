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
make_binary "$CANDIDATE" 42.7.123 compatible
RELEASE=42.7.123
before=$(sha256sum "$CONFIG")
candidate_compatibility "$CANDIDATE" "$CONFIG"
[[ $(binary_version "$CANDIDATE") == 42.7.123 && $(sha256sum "$CONFIG") == "$before" ]]
printf 'ok - future 42.7.123 strict candidate compatibility accepted without a version pin\n'
load_installation() { candidate_compatibility "$BIN" "$CONFIG"; }
fetch_release() { RELEASE=${fixture_latest:-42.7.123}; }
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
[[ $(binary_version "$BIN") == 42.7.123 && $(sha256sum "$CONFIG") == "$before" ]]
printf 'ok - compatible future update activated; TOML byte-identical\n'
fixture_latest=42.7.123
update_manager >"$sandbox/equal.log" 2>&1
grep -q 'already up to date' "$sandbox/equal.log"
printf 'ok - equal version reports already up to date\n'
fixture_latest=3.5.7
assert_rejected 'latest stable older than installed' update_manager
grep -q 'Latest stable 3.5.7 is older than installed 42.7.123; automatic downgrade refused' "$sandbox/refusal.log"
[[ $(binary_version "$BIN") == 42.7.123 ]]
make_binary "$BIN" 3.5.9 compatible
fixture_latest=3.5.7
assert_rejected 'stable 3.5.7 versus installed 3.5.9 downgrade' update_manager
fixture_latest=42.7.123
for behavior in incompatible noop mutate; do
    make_binary "$CANDIDATE" 42.7.123 "$behavior"
    assert_rejected "future candidate $behavior" update_manager
    [[ $(binary_version "$BIN") == 3.5.9 ]]
done
make_binary "$CANDIDATE" 42.7.123 compatible
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
# Use the production selector, not the fixture override.
fetch_release_real() {
    (source ./telemt-web-manager.sh; TMP="$sandbox/tmp"; fetch_release)
}
# Public latest metadata must reject both draft and prerelease flags.
for state in prerelease draft; do
    curl() { printf '{"tag_name":"42.7.123","draft":%s,"prerelease":%s}' \
        "$( [[ $state == draft ]] && printf true || printf false )" \
        "$( [[ $state == prerelease ]] && printf true || printf false )" >"$sandbox/tmp/release.json"; }
    assert_rejected "latest metadata $state" fetch_release_real
 done
