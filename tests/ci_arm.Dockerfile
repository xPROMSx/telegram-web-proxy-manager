# syntax=docker/dockerfile:1
# The existing 24.04 qemu-user contract needs no kernel, systemd or boot disk.
FROM ubuntu:24.04
RUN --mount=type=secret,id=system_ca,mode=0444,target=/run/secrets/system-ca.pem \
    sed -i 's|http://|https://|g' /etc/apt/sources.list.d/ubuntu.sources && \
    apt-get -o Acquire::https::CaInfo=/run/secrets/system-ca.pem -o APT::Update::Error-Mode=any update && \
    DEBIAN_FRONTEND=noninteractive apt-get -o Acquire::https::CaInfo=/run/secrets/system-ca.pem install -y --no-install-recommends \
    ca-certificates bash python3 util-linux openssl qemu-user libc6-arm64-cross libgcc-s1-arm64-cross && \
    rm -rf /var/lib/apt/lists/*
RUN mkdir -p /lib/aarch64-linux-gnu && \
    ln -s /usr/aarch64-linux-gnu/lib/ld-linux-aarch64.so.1 /lib/ld-linux-aarch64.so.1 && \
    for library in libc.so.6 libm.so.6 libgcc_s.so.1; do \
        ln -s /usr/aarch64-linux-gnu/lib/$library /lib/aarch64-linux-gnu/$library; done
