#!/bin/sh
# Install the appliance's own system files (vme-insight-setup, -apply, -update, the boot and update-check
# services, the login message) from /opt/vme-insight/appliance/rootfs. vme-insight-update runs this after
# copying in a new release. After updating from 0.6.0 or earlier, run it once yourself:
#
#   sudo sh /opt/vme-insight/appliance/install-system-files.sh && sudo vme-insight-apply
#
# Your settings (/etc/vme-insight/appliance.yaml) and the image's third-party notice are never replaced.
set -eu
[ "$(id -u)" = 0 ] || { echo "Run it with sudo." >&2; exit 1; }
cd /opt/vme-insight/appliance/rootfs
find . -type f | sort | while read -r f; do
  dest="/${f#./}"
  case "$dest" in
    /etc/vme-insight/appliance.yaml|/usr/share/doc/vme-insight-appliance/NOTICE) continue ;;
    /usr/local/sbin/*|/etc/update-motd.d/*) mode=755 ;;
    *) mode=644 ;;
  esac
  cmp -s "$f" "$dest" 2>/dev/null && continue
  install -D -o root -g root -m "$mode" "$f" "$dest"
  echo "installed $dest"
done
systemctl daemon-reload
systemctl enable --quiet vme-insight-firstboot.service vme-insight-update-check.timer
