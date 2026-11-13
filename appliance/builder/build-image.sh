#!/usr/bin/env bash
# Runs inside the builder container (see appliance/build.sh). /build holds stage/, cache/ and out/.
set -euo pipefail
BASE_URL=https://cloud.debian.org/images/cloud/trixie/latest
BASE=debian-13-genericcloud-amd64.qcow2
DISK_SIZE=20G
OUT=/build/out/vme-insight-appliance-$VERSION.qcow2
WORK=/build/work.qcow2
export LIBGUESTFS_BACKEND=direct

echo "-- Debian 13 cloud image"
cd /build/cache
curl -fsSL -o SHA512SUMS "$BASE_URL/SHA512SUMS"
if ! grep " $BASE\$" SHA512SUMS | sha512sum -c --status 2>/dev/null; then
  curl -fsSL -o "$BASE" "$BASE_URL/$BASE"
  grep " $BASE\$" SHA512SUMS | sha512sum -c
fi
echo "   $(grep " $BASE\$" SHA512SUMS | cut -c1-32)... verified"

echo "-- grow to $DISK_SIZE (cloud-init grows it again to the VM's disk size at first boot)"
rm -f "$WORK" && qemu-img create -q -f qcow2 "$WORK" "$DISK_SIZE"
virt-resize --quiet --expand /dev/sda1 "/build/cache/$BASE" "$WORK"

echo "-- install and configure (slow without KVM)"
virt-customize -a "$WORK" --network --memsize 2048 --smp 2 \
  --run-command 'apt-get update -q' \
  --install docker.io,docker-compose,qemu-guest-agent,zstd \
  --copy-in /build/stage/vme-insight:/opt \
  --copy-in /build/stage/rootfs:/tmp \
  --run-command 'cp -r --no-preserve=all /tmp/rootfs/. / && rm -rf /tmp/rootfs' \
  --run-command 'chown -R root:root /opt/vme-insight && chmod -R u+rwX,go+rX,go-w /opt/vme-insight' \
  --run-command 'chmod 755 /usr/local/sbin/vme-insight-* /etc/update-motd.d/60-vme-insight' \
  --run-command 'bad=$(find /etc /usr /opt/vme-insight -xdev ! -type l \( ! -user root -o -perm -o+w \) ! -path "/usr/share/zoneinfo/*" | head -5); if [ -n "$bad" ]; then echo "not root-owned or world-writable: $bad"; exit 1; fi' \
  --run-command 'systemctl enable docker.service qemu-guest-agent.service vme-insight-firstboot.service' \
  --run-command 'apt-get clean && rm -rf /var/lib/apt/lists/*' \
  --run-command 'cloud-init clean --logs --machine-id || true' \
  --run-command 'rm -f /etc/ssh/ssh_host_* && truncate -s 0 /etc/machine-id' \
  --run-command 'rm -f /root/.bash_history && find /var/log -type f -exec truncate -s 0 {} +'

echo "-- zero free space and compress"
virt-sparsify --quiet --in-place "$WORK"
qemu-img convert -q -c -O qcow2 "$WORK" "$OUT"
rm -f "$WORK"
cd /build/out && sha256sum "$(basename "$OUT")" > SHA256SUMS
qemu-img info "$OUT" | grep -E 'virtual size|disk size'
if [ -n "${OWNER:-}" ]; then chown -R "$OWNER" /build/out /build/cache; fi
