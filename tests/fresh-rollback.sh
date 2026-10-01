#!/usr/bin/env bash
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
fixture=$(mktemp -d)
trap 'rm -rf -- "$fixture"' EXIT
python3 tests/three_x_ui.py "$fixture/nginx" --script x-ui-latest.sh
for failure in late after-user directories cleanup userdel groupdel identity partial-useradd stop preexisting-user preexisting-path; do
    FIXTURE_FAILURE=$failure bash tests/fresh.sh "$fixture/nginx"
done
