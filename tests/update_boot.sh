#!/usr/bin/env bash
# REAL boot + hard power-loss recovery. No privileged Docker/host mounts/network.
set -Eeuo pipefail
cd -- "$(dirname -- "$0")/.."
command -v docker >/dev/null
family=${1:?Ubuntu 24.04 or 26.04 required}
[[ $family == 24.04 || $family == 26.04 ]]
work=${TELEMT_UPDATE_BOOT_DIR:?Private outside-checkout boot evidence required}
artifacts=${TELEMT_UPDATE_ARTIFACTS:?Verified official artifacts required}
mkdir -p "$work"
ca=${SSL_CERT_FILE:-/etc/ssl/certs/ca-certificates.crt}
docker build --secret "id=system_ca,src=$ca" --build-arg "UBUNTU_VERSION=$family" \
    -f tests/update_boot.Dockerfile -t "twm-boot:$family" . >"$work/build-$family.log" 2>&1
container=$(docker create "twm-boot:$family")
trap 'docker rm -f "$container" >/dev/null 2>&1' EXIT
docker export "$container" >"$work/ubuntu-$family.tar"
docker rm "$container" >/dev/null
trap - EXIT
docker run --rm --network=none -v "$work:/work" -v "$PWD:/src:ro" "twm-boot:$family" \
    bash /src/tests/update_boot_prepare.sh "$family"
python3 tests/update_boot_host.py "$family" "$work" "$PWD" "$artifacts"
# Private guest disks contain fixture keys and are large. Preserve bounded boot
# logs, but reclaim only these exact generated files after all assertions pass.
rm -- "$work/ubuntu-$family.tar" "$work/boot-$family/disk.img"
