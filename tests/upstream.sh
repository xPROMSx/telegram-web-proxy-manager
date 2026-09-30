#!/usr/bin/env bash
# CI only. Verify published upstream binary before executing its config validator.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
# shellcheck source=telemt-web-manager.sh
source ./telemt-web-manager.sh
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT
DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10 RELEASE=3.5.9 DATA="$TMP/data"
mkdir -p "$DATA/public"
printf '<!doctype html><title>Welcome</title>' >"$DATA/public/index.html"
curl --proto '=https' -fsS --retry 2 --max-time 60 \
    https://api.github.com/repos/telemt/telemt/releases/tags/3.5.9 -o "$TMP/release.json"
download_candidate
for SOCKS in direct 127.0.0.1:1080; do
    secret=$(openssl rand -hex 16)
    generate_config "$secret" >"$TMP/config.toml"
    unset secret
    candidate_healthcheck "$CANDIDATE" "$TMP/config.toml"
done
printf 'ok - verified Telemt 3.5.9 accepts generated direct and SOCKS configurations\n'
