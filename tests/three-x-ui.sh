#!/usr/bin/env bash
# Test the complete emitted config of the pinned Fresh Install script.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
fixture_dir=$(mktemp -d)
trap 'rm -rf -- "$fixture_dir"' EXIT
script=x-ui-latest.sh
[[ $# -le 1 ]]
for profile in legacy webroot; do
    root="$fixture_dir/$profile"
    source_args=()
    if [[ $# == 1 ]]; then source_args=(--source "$1/$profile"); fi
    python3 tests/three_x_ui.py "$root" --script "$script" --profile "$profile" "${source_args[@]}"
    bash tests/fresh.sh "$root"
    bash tests/nginx-rollback.sh "$root"
    bash tests/acme.sh "$root"
    bash tests/nginx.sh "$root"
    printf 'ok - full %s %s topology: install/idempotence/ACME/rollback/real Nginx IPv4+IPv6\n' "$profile" "$script"
done
# The reported v1.6.2 SNI topology, without repeating unrelated lifecycle suites.
root="$fixture_dir/v1.6.2"
source_args=()
if [[ $# == 1 ]]; then source_args=(--source "$1/v1.6.2"); fi
python3 tests/three_x_ui.py "$root" --script "$script" --profile v1.6.2 "${source_args[@]}"
bash tests/nginx.sh "$root"
