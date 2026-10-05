#!/usr/bin/env bash
# Actual official ARM ELF version/strict parser under qemu-user. No native ARM runtime claim.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
artifacts=${TELEMT_UPDATE_ARTIFACTS:?Verified official artifacts required}
family=${1:-24.04}
[[ $family == 24.04 || $family == 26.04 ]]
# Literal child-shell variables must expand inside the disposable container.
# shellcheck disable=SC2016
docker run --rm --network=none --read-only --cap-drop=ALL \
    --cap-add=DAC_OVERRIDE --cap-add=CHOWN --cap-add=SETUID --cap-add=SETGID --cap-add=SETPCAP \
    --security-opt=no-new-privileges --pids-limit=128 --memory=512m --cpus=1 \
    --tmpfs /tmp:rw,nosuid,nodev,size=64m \
    -v "$PWD:/src:ro" -v "$artifacts/aarch64/candidate:/official-candidate:ro" \
    "twm-boot:$family" bash -c '
set -Eeuo pipefail
source /src/telemt-web-manager.sh
stage=setup
temporary=$(mktemp -d)
finish() { local result=$?; if (( result )); then printf "ARM fixture failed at %s; exit=%s (private output withheld)\n" "$stage" "$result" >&2; fi; rm -rf -- "$temporary"; }
trap finish EXIT
chmod 0755 "$temporary"
install -m 0755 /official-candidate "$temporary/telemt"
[[ $(sha256sum "$temporary/telemt" | cut -d" " -f1) == d280700fe1508f4b1e13119d422c8a5dba20fd38a71e099fbcf68791c09903e3 ]]
DATA="$temporary/data" DOMAIN=proxy.example.com PUBLIC_IP=203.0.113.10
mkdir -p "$DATA/public" "$DATA/state"
chmod 0750 "$DATA" "$DATA/public" "$DATA/state"
chown 0:65534 "$DATA" "$DATA/public"
chown 65534:65534 "$DATA/state"
printf "<!doctype html><title>Welcome</title>\n" >"$DATA/public/index.html"
chmod 0440 "$DATA/public/index.html"
chown 0:65534 "$DATA/public/index.html"
token=$(openssl rand -hex 16)
generate_config "$token" >"$temporary/config.toml"
unset token
printf "__telemt_web_manager_unknown_contract = true\n" >"$temporary/unknown.toml"
cat "$temporary/config.toml" >>"$temporary/unknown.toml"
chown 0:65534 "$temporary/config.toml" "$temporary/unknown.toml"
chmod 0640 "$temporary/config.toml" "$temporary/unknown.toml"
probe() {
    (cd "$DATA"; timeout 60 setpriv --no-new-privs --reuid=65534 --regid=65534 --clear-groups --bounding-set=-all \
        env -i PATH=/usr/bin:/bin LANG=C HOME=/tmp qemu-aarch64 "$temporary/telemt" "$@")
}
stage=version
[[ $(probe --version) == "telemt 3.5.13" ]]
for SOCKS in direct 127.0.0.1:1080; do
    # Direct and SOCKS managed TOML are generated with a new private fixture secret.
    token=$(openssl rand -hex 16); generate_config "$token" >"$temporary/config.toml"; unset token
    printf "__telemt_web_manager_unknown_contract = true\n" >"$temporary/unknown.toml"
    cat "$temporary/config.toml" >>"$temporary/unknown.toml"
    before=$(sha256sum "$temporary/config.toml")
    stage="healthcheck-$SOCKS"
    probe healthcheck "$temporary/config.toml" >"$temporary/healthcheck.log" 2>&1
    set +e
    probe healthcheck "$temporary/unknown.toml" >/dev/null 2>&1
    result=$?
    set -e
    stage="unknown-key-$SOCKS"
    [[ $result == 1 && $(sha256sum "$temporary/config.toml") == "$before" ]]
done
printf "REAL official aarch64 3.5.13: archive/ELF identity, emulated version, direct/SOCKS strict healthcheck, unknown-key exit=1, unchanged TOML: PASS\n"
printf "ARM limitation: qemu-user parser coverage only; full native ARM systemd/CAP/firewall/WEB runtime is not claimed.\n"
'
