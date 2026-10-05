#!/usr/bin/env bash
# Test the complete emitted config of the pinned Fresh Install script.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
fixture_dir=$(mktemp -d)
trap 'rm -rf -- "$fixture_dir"' EXIT
script=x-ui-latest.sh
root="$fixture_dir/$script"
python3 tests/three_x_ui.py "$root" --script "$script"
bash tests/fresh.sh "$root"
bash tests/nginx-rollback.sh "$root"
bash tests/acme.sh "$root"
bash tests/nginx.sh "$root"
printf 'ok - full %s emitted topology: install/idempotence/real Nginx IPv4+IPv6\n' "$script"
