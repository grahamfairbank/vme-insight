#!/usr/bin/env bash
# Boot the built appliance under QEMU with a NoCloud seed (the same way Morpheus delivers cloud-init
# on HVM clusters) and leave it running for checks.
#
#   appliance/test/boot-test.sh <image.qcow2> <appliance.yaml> <ssh-public-key>   start
#   appliance/test/boot-test.sh stop                                               stop and clean up
#
# ISOLATED=1 cuts the VM off from every network except two forwards, to test proxy settings:
#   10.0.2.100:3128 -> test/proxy.py in the container (logs each destination: docker logs <name>)
#   10.0.2.101:443  -> $MORPHEUS ("host port" of the Morpheus appliance; use url: https://10.0.2.101)
# Set proxy.url: http://10.0.2.100:3128 in appliance.yaml.
#
# MEM (MiB, default 4096) and CPUS (default 4) set the VM size.
#
# Check it with appliance/test/check.sh <ssh-private-key>. Ports are also published on 127.0.0.1:
# 2222 (SSH, user debian), 13000 (Grafana) and 13443 (https), where Docker publishing allows it.
# appliance.yaml holds credentials: keep it mode 600 and outside the repo.
set -euo pipefail
NAME=vme-insight-appliance-test
if [ "${1:-}" = stop ]; then docker rm -f "$NAME" >/dev/null 2>&1 || true; echo stopped; exit 0; fi
IMG=$(realpath "$1"); SETTINGS=$(realpath "$2"); KEY=$(cat "$3")
T=$(mktemp -d); chmod 700 "$T"
python3 - "$SETTINGS" "$KEY" > "$T/user-data" <<'EOF'
import sys
settings = open(sys.argv[1]).read()
print("#cloud-config")
print("ssh_authorized_keys:")
print(f"  - {sys.argv[2]}")
print("write_files:")
print("  - path: /etc/vme-insight/appliance.yaml")
print("    permissions: '0600'")
print("    content: |")
for line in settings.splitlines():
    print("      " + line)
EOF
printf 'instance-id: %s-%s\nlocal-hostname: vme-insight-test\n' "$NAME" "$(date +%s)" > "$T/meta-data"
docker rm -f "$NAME" >/dev/null 2>&1 || true
NET="user,id=n0"
if [ "${ISOLATED:-}" = 1 ]; then
  NET="user,id=n0,restrict=on,guestfwd=tcp:10.0.2.100:3128-cmd:python3 /test/relay.py 127.0.0.1 3128,guestfwd=tcp:10.0.2.101:443-cmd:python3 /test/relay.py ${MORPHEUS:?set MORPHEUS=\"host port\"}"
  # cmd: starts a relay per connection (a tcp: target would carry only the first one)
fi
docker run -d --name "$NAME" -v "$IMG:/img/base.qcow2:ro" -v "$T:/seed" -v "$(dirname "$(realpath "$0")"):/test:ro" -e ISOLATED="${ISOLATED:-}" -e NET="$NET" -e MEM="${MEM:-4096}" -e CPUS="${CPUS:-4}" \
  -p 127.0.0.1:2222:2222 -p 127.0.0.1:13000:13000 -p 127.0.0.1:13443:13443 \
  vme-insight-appliance-builder bash -c '
    set -e
    [ "$ISOLATED" = 1 ] && { python3 -u /test/proxy.py 3128 & sleep 1; }
    genisoimage -quiet -output /seed/seed.iso -volid cidata -joliet -rock /seed/user-data /seed/meta-data
    qemu-img create -q -f qcow2 -b /img/base.qcow2 -F qcow2 /tmp/disk.qcow2 30G
    exec qemu-system-x86_64 -accel tcg,thread=multi -cpu max -m "${MEM:-4096}" -smp "${CPUS:-4}" -nographic \
      -drive file=/tmp/disk.qcow2,if=virtio -drive file=/seed/seed.iso,media=cdrom \
      -netdev "$NET,hostfwd=tcp::2222-:22,hostfwd=tcp::13000-:3000,hostfwd=tcp::13443-:3443" \
      -device virtio-net-pci,netdev=n0' >/dev/null
# the seed holds credentials: remove our copy once QEMU has built the ISO
( sleep 60; rm -rf "$T" ) &
echo "booting; console: docker logs -f $NAME"
