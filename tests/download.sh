#!/usr/bin/env bash
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
# shellcheck source=telemt-web-manager.sh
source ./telemt-web-manager.sh
SANDBOX=$(mktemp -d)
trap 'rm -rf -- "$SANDBOX"' EXIT
TMP="$SANDBOX/tmp" DATA="$SANDBOX/data" RELEASE=3.5.9
mkdir "$TMP" "$DATA" "$SANDBOX/archive"
printf '#!/bin/sh\nexit 0\n' >"$SANDBOX/archive/telemt"
tar -czf "$SANDBOX/source.tar.gz" -C "$SANDBOX/archive" telemt
curl() { cp "$SANDBOX/source.tar.gz" "$TMP/asset.tar.gz"; }
binary_version() { touch "$SANDBOX/executed"; printf '%s\n' "$RELEASE"; }
metadata() {
    local digest=$1 arch
    arch=$(uname -m)
    jq -n --arg digest "sha256:$digest" --arg asset "telemt-$arch-linux-gnu.tar.gz" \
        '{assets:[{name:$asset,digest:$digest,browser_download_url:("https://github.com/telemt/telemt/releases/download/3.5.9/"+$asset)}]}' >"$TMP/release.json"
}
metadata "$(printf '%064d' 0)"
set +e
(download_candidate) >"$SANDBOX/mismatch.log" 2>&1
result=$?
set -e
[[ $result != 0 && ! -e $SANDBOX/executed ]]
metadata "$(sha256sum "$SANDBOX/source.tar.gz" | cut -d' ' -f1)"
download_candidate
[[ -e $SANDBOX/executed ]]
rm "$SANDBOX/executed" "$SANDBOX/archive/telemt"
ln -s /bin/sh "$SANDBOX/archive/telemt"
tar -czf "$SANDBOX/source.tar.gz" -C "$SANDBOX/archive" telemt
metadata "$(sha256sum "$SANDBOX/source.tar.gz" | cut -d' ' -f1)"
set +e
(download_candidate) >"$SANDBOX/symlink.log" 2>&1
result=$?
set -e
[[ $result != 0 && ! -e $SANDBOX/executed ]]
printf 'ok - digest mismatch and symlink archive never execute; valid digest passes\n'

# SC2016: preserve positional arguments for the generated candidate stub.
# shellcheck disable=SC2016
printf '#!/bin/sh\ncat "$2" >&2\nexit 1\n' >"$SANDBOX/reject"
chmod 0755 "$SANDBOX/reject"
secret=$(openssl rand -hex 16)
printf '%s\n' "$secret" >"$SANDBOX/config"
if candidate_healthcheck "$SANDBOX/reject" "$SANDBOX/config" >"$SANDBOX/healthcheck.log" 2>&1; then exit 1; fi
[[ ! -s $SANDBOX/healthcheck.log ]]
printf 'ok - candidate diagnostics containing credentials are suppressed\n'
