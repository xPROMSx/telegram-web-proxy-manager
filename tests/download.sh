#!/usr/bin/env bash
# Real pinned asset integrity plus download/execution-boundary fixtures.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
# shellcheck source=telemt-web-manager.sh
source ./telemt-web-manager.sh
SANDBOX=$(mktemp -d)
trap 'rm -rf -- "$SANDBOX"' EXIT
TMP="$SANDBOX/tmp" DATA="$SANDBOX/data"
mkdir "$TMP" "$DATA" "$SANDBOX/archive"
download_candidate
[[ $(binary_version "$CANDIDATE") == "$SUPPORTED_TELEMT_VERSION" ]]
cp "$TMP/asset.tar.gz" "$SANDBOX/official.tar.gz"
printf 'ok - production downloader verifies actual pinned asset digest and exact binary version\n'
eval "$(declare -f binary_version | sed '1s/binary_version/official_binary_version/')"
binary_version() { touch "$SANDBOX/executed"; official_binary_version "$@"; }
fixture_source="$SANDBOX/official.tar.gz"
curl() {
    local argument url=''
    for argument in "$@"; do
        if [[ $argument == https://* ]]; then url=$argument; fi
    done
    [[ $url == "https://github.com/telemt/telemt/releases/download/$SUPPORTED_TELEMT_VERSION/telemt-$(uname -m)-linux-gnu.tar.gz" ]]
    printf '%s\n' "$url" >"$SANDBOX/requested-url"
    cp "$fixture_source" "$TMP/asset.tar.gz"
}
assert_download_refused() {
    local label=$1 result
    rm -f "$SANDBOX/executed" "$TMP/telemt"
    set +e
    (set -Eeuo pipefail; download_candidate) >"$SANDBOX/refusal.log" 2>&1
    result=$?
    set -e
    [[ $result != 0 && ! -e $SANDBOX/executed ]]
    printf 'ok - %s refused before candidate execution\n' "$label"
}
printf corrupted >"$SANDBOX/corrupted.tar.gz"
fixture_source="$SANDBOX/corrupted.tar.gz"
assert_download_refused 'real SHA256 mismatch against immutable production pin'
fixture_source="$SANDBOX/official.tar.gz"
download_candidate
[[ -f $SANDBOX/executed ]]
grep -Fq "/releases/download/$SUPPORTED_TELEMT_VERSION/" "$SANDBOX/requested-url"
printf 'ok - downloader constructs only the pinned official URL; no latest/asset metadata selection\n'
# An unsafe archive never reaches execution; test_safety.py separately exercises
# the real extractor's symlink/traversal/layout refusals with no hash mock.
ln -s /bin/sh "$SANDBOX/archive/telemt"
tar -czf "$SANDBOX/unsafe.tar.gz" -C "$SANDBOX/archive" telemt
fixture_source="$SANDBOX/unsafe.tar.gz"
assert_download_refused 'untrusted symlink archive'
fixture_source="$SANDBOX/official.tar.gz"
binary_version() { printf '42.7.123\n'; }
set +e
(set -Eeuo pipefail; download_candidate) >"$SANDBOX/version-refusal.log" 2>&1
result=$?
set -e
[[ $result != 0 ]]
grep -q 'Candidate differs from supported Telemt version' "$SANDBOX/version-refusal.log"
printf 'ok - digest-valid candidate with non-pinned version is refused before installation\n'
# Preserve credential-bearing healthcheck diagnostic suppression.
# shellcheck disable=SC2016
printf '#!/bin/sh\ncat "$2" >&2\nexit 1\n' >"$SANDBOX/reject"
chmod 0755 "$SANDBOX/reject"
secret=$(openssl rand -hex 16)
printf '%s\n' "$secret" >"$SANDBOX/config"
if candidate_healthcheck "$SANDBOX/reject" "$SANDBOX/config" >"$SANDBOX/healthcheck.log" 2>&1; then exit 1; fi
[[ ! -s $SANDBOX/healthcheck.log ]]
printf 'ok - candidate diagnostics containing credentials are suppressed\n'
