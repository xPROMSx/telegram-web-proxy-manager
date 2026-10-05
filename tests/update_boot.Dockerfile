# syntax=docker/dockerfile:1
ARG UBUNTU_VERSION=24.04
FROM ubuntu:${UBUNTU_VERSION}
RUN --mount=type=secret,id=system_ca,mode=0444,target=/run/secrets/system-ca.pem \
    sed -i 's|http://|https://|g' /etc/apt/sources.list.d/ubuntu.sources && \
    apt-get -o Acquire::https::CaInfo=/run/secrets/system-ca.pem -o APT::Update::Error-Mode=any update && \
    DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::https::CaInfo=/run/secrets/system-ca.pem install -y --no-install-recommends \
    ca-certificates systemd systemd-sysv dbus linux-image-generic initramfs-tools \
    python3 bash util-linux iproute2 iptables nftables conntrack curl openssl jq dnsutils \
    nginx libnginx-mod-stream certbot passwd findutils kmod qemu-system-x86 qemu-user e2fsprogs shellcheck \
    gcc libc6-dev libc6-arm64-cross libgcc-s1-arm64-cross \
    && rm -rf /var/lib/apt/lists/*
# qemu -L rewrites open("/") but not subsequent relative openat calls used by
# Rust canonicalize. Install the fixed ARM loader/libraries at their ordinary
# paths instead; tests keep the entire image read-only.
RUN mkdir -p /lib/aarch64-linux-gnu && \
    ln -s /usr/aarch64-linux-gnu/lib/ld-linux-aarch64.so.1 /lib/ld-linux-aarch64.so.1 && \
    for library in libc.so.6 libm.so.6 libgcc_s.so.1; do \
        ln -s /usr/aarch64-linux-gnu/lib/$library /lib/aarch64-linux-gnu/$library; done
