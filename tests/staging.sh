#!/usr/bin/env bash
# Pinned official binary config/staging healthchecks; no real runtime startup.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
# shellcheck source=telemt-web-manager.sh
source ./telemt-web-manager.sh
TMP=$(mktemp -d)
trap 'rm -rf -- "$TMP"' EXIT
DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10 DATA="$TMP/production-data"
download_candidate
secret=$(openssl rand -hex 16)
for SOCKS in direct 127.0.0.1:1080; do
    # Reproduce the old invalid ordering with no production filesystem.
    generate_config "$secret" >"$TMP/old.toml"
    mkdir -p "$TMP/empty-cwd"
    if candidate_healthcheck "$CANDIDATE" "$TMP/old.toml" "$TMP/empty-cwd"; then
        die 'Old missing static-directory ordering unexpectedly passed'
    fi
    [[ ! -e $DATA ]]
    prepare_compatibility_data "$TMP/compat-data"
    generate_config "$secret" "$TMP/compat-data" >"$TMP/staged.toml"
    candidate_compatibility "$CANDIDATE" "$TMP/staged.toml" "$TMP/compat-data"
    printf 'ok - official pinned Telemt %s config healthcheck: staged static_directory + strict unknown-key rejection (%s)\n' "$RELEASE" "$SOCKS"
    mv "$TMP/compat-data/public" "$TMP/compat-data/saved-public"
    if candidate_compatibility "$CANDIDATE" "$TMP/staged.toml" "$TMP/compat-data"; then die 'Missing static directory accepted'; fi
    mv "$TMP/compat-data/saved-public" "$TMP/compat-data/public"
    mv "$TMP/compat-data/public/index.html" "$TMP/compat-data/public/saved-index"
    if candidate_compatibility "$CANDIDATE" "$TMP/staged.toml" "$TMP/compat-data"; then die 'Missing static index accepted'; fi
    mv "$TMP/compat-data/public/saved-index" "$TMP/compat-data/public/index.html"
    printf 'ok - official binary healthcheck rejects missing static_directory and index; old ordering fails before issuance (%s)\n' "$SOCKS"
    # Root mismatch and symlink escape must not turn staging into a weaker contract.
    if candidate_compatibility "$CANDIDATE" "$TMP/staged.toml" "$DATA"; then die 'Unexpected data root accepted'; fi
    rm -rf -- "$TMP/compat-data"
    ln -s "$TMP/empty-cwd" "$TMP/compat-data"
    if prepare_compatibility_data "$TMP/compat-data"; then die 'Symlink staging accepted'; fi
    rm -- "$TMP/compat-data"
    REAL_CANDIDATE="$CANDIDATE" FIXTURE_SOCKS="$SOCKS" bash tests/fresh.sh
    REAL_CANDIDATE="$CANDIDATE" FIXTURE_SOCKS="$SOCKS" FIXTURE_INCOMPATIBLE=1 bash tests/fresh.sh
    for missing in directory index; do
        REAL_CANDIDATE="$CANDIDATE" FIXTURE_SOCKS="$SOCKS" FIXTURE_MISSING_STATIC="$missing" bash tests/fresh.sh
    done
done
unset secret
printf 'ok - pinned Telemt %s staging healthcheck + fresh transaction fixtures; service/path health and journal transport mocked\n' "$RELEASE"

if [[ -n ${TELEMT_TEST_EVIDENCE_DIR:-} ]]; then printf '%s\n' "$(binary_version "$CANDIDATE")" >"$TELEMT_TEST_EVIDENCE_DIR/staging.version"; fi
