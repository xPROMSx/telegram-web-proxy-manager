#!/usr/bin/env bash
# Version/parser contracts, synthetic trusted fixtures. Universal update file
# activation/rollback and future 4.0.0 run in update_transactions.py and real boot.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
# shellcheck source=telemt-web-manager.sh
source ./telemt-web-manager.sh
sandbox=$(mktemp -d)
trap 'rm -rf -- "$sandbox"' EXIT
TMP="$sandbox/tmp" DATA="$sandbox/data" BIN="$sandbox/installed" CONFIG="$sandbox/config.toml"
DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10
mkdir -p "$TMP" "$DATA/state" "$DATA/public"
printf '<!doctype html><title>Welcome</title>\n' >"$DATA/public/index.html"
generate_config "$(openssl rand -hex 16)" >"$CONFIG"
cp "$CONFIG" "$sandbox/original.toml"
make_binary() {
    python3 - "$1" "$2" "$3" <<'PY'
from pathlib import Path
import sys
path, version, behavior = sys.argv[1:]; path=Path(path)
path.write_text('#!/usr/bin/env python3\nimport sys,tomllib\nfrom pathlib import Path\n'
 + 'version='+repr(version)+'\nbehavior='+repr(behavior)+'\n'+'''if sys.argv[1:] == ['--version']:
 print('Telemt '+version);sys.exit(0)
if len(sys.argv)==3 and sys.argv[1]=='healthcheck':
 p=Path(sys.argv[2]); c=tomllib.loads(p.read_text())
 if behavior=='mutate':p.write_text('modified');sys.exit(0)
 if behavior=='incompatible':sys.exit(1)
 if behavior=='noop':sys.exit(0)
 sys.exit(1 if '__telemt_web_manager_unknown_contract' in c else 0)
sys.exit(1)
''');path.chmod(0o755)
PY
}
for version in 3.5.12 3.5.13 4.0.0 42.7.123; do
    make_binary "$BIN" "$version" compatible
    [[ $(binary_version "$BIN") == "$version" ]]
done
[[ $(helper version-compare 4.0.0 3.5.13) == 1 ]]
[[ $(helper version-compare 3.5.12 3.5.13) == -1 ]]
[[ $(helper version-compare 3.5.13+custom 3.5.13) == 0 ]]
printf 'ok - SemVer all-series ordering; custom build equal precedence remains distinct identity\n'
for behavior in compatible incompatible noop mutate; do
    cp "$sandbox/original.toml" "$CONFIG"
    make_binary "$BIN" "$SUPPORTED_TELEMT_VERSION" "$behavior"
    set +e
    (set -Eeuo pipefail; candidate_compatibility "$BIN" "$CONFIG") >"$sandbox/parser.log" 2>&1
    result=$?
    set -e
    if [[ $behavior == compatible ]]; then [[ $result == 0 ]] && cmp "$CONFIG" "$sandbox/original.toml"
    else [[ $result != 0 ]]; fi
    printf 'ok - trusted synthetic parser %s contract\n' "$behavior"
done
cp "$sandbox/original.toml" "$CONFIG"
for value in '01.2.3' '1.2' '4.0.0 extra'; do
    make_binary "$BIN" "$value" compatible
    if binary_version "$BIN" >/dev/null; then exit 1; fi
done
if [[ -n ${REAL_CANDIDATE:-} ]]; then
    candidate_compatibility "$REAL_CANDIDATE" "$CONFIG"
    cmp "$CONFIG" "$sandbox/original.toml"
    printf 'ok - REAL official Install baseline %s strictly accepts unchanged managed TOML; universal 3.5.13 Update covered in real boot\n' "$SUPPORTED_TELEMT_VERSION"
fi
# Objective lifecycle is mocked here; local receipt identity supplies the version.
load_installation() { return 0; }
installed_release_identity() { printf 4.0.0; }
renewal_scheduler_status() { return 0; }
systemctl() { if [[ $* == *MainPID* ]]; then printf '%s\n' "$$"; fi; }
listener_ready() { return 0; }
path_health() { return 0; }
recent_logs() { return 0; }
openssl() { return 0; }
check_manager >"$sandbox/check.log" 2>&1
grep -Fq 'installed Telemt: 4.0.0; Install baseline: 3.5.12' "$sandbox/check.log"
grep -q 'Check result: OK' "$sandbox/check.log"
printf 'ok - Check uses local receipt/objective health, with no baseline equality or GitHub query\n'
