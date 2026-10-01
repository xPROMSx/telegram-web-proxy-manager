#!/usr/bin/env bash
# CI only. Verify published upstream binary before executing its config validator.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
# shellcheck source=telemt-web-manager.sh
source ./telemt-web-manager.sh
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT
DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10 DATA="$TMP/data"
mkdir -p "$DATA/public"
printf '<!doctype html><title>Welcome</title>' >"$DATA/public/index.html"
for RELEASE in 3.5.7 3.5.9; do
rm -f -- "$TMP/telemt"
curl --proto '=https' -fsS --retry 2 --max-time 60 \
    "https://api.github.com/repos/telemt/telemt/releases/tags/$RELEASE" -o "$TMP/release.json"
download_candidate
for SOCKS in direct 127.0.0.1:1080; do
    secret=$(openssl rand -hex 16)
    generate_config "$secret" >"$TMP/config.toml"
    unset secret
    candidate_compatibility "$CANDIDATE" "$TMP/config.toml"
    sed '/^config_strict = true/a manager_unknown_key = true' "$TMP/config.toml" >"$TMP/unknown.toml"
    if candidate_healthcheck "$CANDIDATE" "$TMP/unknown.toml"; then
        printf 'FAIL - strict configuration accepted an unknown key\n' >&2; exit 1
    fi
done
printf 'ok - verified Telemt %s accepts strict direct/SOCKS contracts and rejects unknown keys\n' "$RELEASE"
done
