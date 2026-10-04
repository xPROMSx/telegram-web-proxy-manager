#!/usr/bin/env bash
# Runs ONLY inside the disposable Docker image; materializes an actual ext4 VM.
set -Eeuo pipefail
family=$1
mkdir -p /tmp/twm-guest
cd /tmp/twm-guest
tar -xf "/work/ubuntu-$family.tar"
printf 'virtio_pci\nvirtio_blk\next4\n9p\n9pnet\n9pnet_virtio\n' >>etc/initramfs-tools/modules
chroot /tmp/twm-guest update-initramfs -u -k all >"/work/prepare-$family.log" 2>&1
mkdir -p opt/telemt-web-manager/lib mnt/source mnt/evidence
cp /src/telemt-web-manager.sh opt/telemt-web-manager/telemt-web-manager.sh
cp /src/lib/safety.py opt/telemt-web-manager/lib/safety.py
chmod 0755 opt/telemt-web-manager/telemt-web-manager.sh
chmod 0644 opt/telemt-web-manager/lib/safety.py
cat >etc/systemd/system/twm-universal-tests.service <<'UNIT'
[Unit]
Wants=network-online.target
After=basic.target network-online.target telemt.service
[Service]
Type=simple
ExecStartPre=/bin/mount -t 9p -o trans=virtio,version=9p2000.L,ro source /mnt/source
ExecStartPre=/bin/mount -t 9p -o trans=virtio,version=9p2000.L,ro evidence /mnt/evidence
ExecStart=/usr/bin/python3 /mnt/source/tests/update_boot_guest.py
TimeoutStartSec=1200
RuntimeMaxSec=1200
UMask=0077
StandardOutput=journal+console
StandardError=journal+console
[Install]
WantedBy=multi-user.target
UNIT
mkdir -p etc/systemd/system/multi-user.target.wants
ln -sf /dev/null etc/systemd/system/systemd-networkd-wait-online.service
ln -s ../twm-universal-tests.service etc/systemd/system/multi-user.target.wants/twm-universal-tests.service
rm -f etc/machine-id
mkdir -p "/work/boot-$family"
cp boot/vmlinuz-*-generic "/work/boot-$family/vmlinuz"
cp boot/initrd.img-*-generic "/work/boot-$family/initrd.img"
truncate -s 6G "/work/boot-$family/disk.img"
mke2fs -q -t ext4 -F -d /tmp/twm-guest "/work/boot-$family/disk.img"
