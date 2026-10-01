#!/usr/bin/env bash
# Capture actual Noble nf_tables stderr in a disposable network namespace.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
test_dir=$(mktemp -d)
trap 'rm -rf -- "$test_dir"' EXIT
iptables-nft --version >"$test_dir/backend"
set +e
# Redirect to private files owned by the invoking CI user, not by sudo.
# shellcheck disable=SC2024
sudo unshare --net -- sh -c 'LC_ALL=C iptables-nft -t raw -D PREROUTING -j TELEMT_NOTRACK' \
    >"$test_dir/stdout" 2>"$test_dir/stderr"
result=$?
set -e
[[ $result != 0 ]]
python3 - "$test_dir" <<'PY'
import contextlib, importlib.util, io, sys
from pathlib import Path
root = Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("safety", "lib/safety.py")
s = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = s
spec.loader.exec_module(s)
backend = (root / "backend").read_text().strip()
diagnostic = (root / "stderr").read_text().strip()
assert "Chain 'TELEMT_NOTRACK' does not exist" in diagnostic, "actual nft diagnostic differs; review required"
record = ("WARN Failed to reconcile conntrack firewall policy generation=1 "
          "error=startup recovery failed: " + diagnostic)
with contextlib.redirect_stdout(io.StringIO()) as out:
    assert s.classify("3.5.9", "ubuntu:24.04", backend, record) == 0
assert "known_nonfatal=1" in out.getvalue()
PY
printf 'ok - actual Ubuntu 24.04 nf_tables missing-chain diagnostic (isolated namespace)\n'
