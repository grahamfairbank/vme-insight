#!/usr/bin/env bash
# Download the exporter packages into installer/dist so HVM hosts install them from the
# vme-insight server instead of GitHub. Run on the vme-insight host.
#   ./tools/fetch-exporter-packages.sh [node_exporter version] [libvirt exporter version] [arch]
set -euo pipefail
NV="${1:-1.12.1}"; LV="${2:-2.6.1}"; A="${3:-amd64}"
DIR="$(cd "$(dirname "$0")/.." && pwd)/installer/dist"
if [ -f /etc/vme-insight/appliance.yaml ] && [ "$(id -u)" != 0 ]; then
  echo "On the vme-insight appliance, run it with sudo: sudo $0 $*" >&2; exit 1
fi
mkdir -p "$DIR"
# On the appliance, use the proxy set in appliance.yaml (vme-insight-apply writes proxy.env).
# A proxy already in the environment (for example from /etc/environment) is kept.
PROXY_ENV=/etc/vme-insight/proxy.env
if [ -z "${https_proxy:-}${HTTPS_PROXY:-}" ] && [ -r "$PROXY_ENV" ]; then
  set -a; . "$PROXY_ENV"; set +a
  echo "using the proxy from $PROXY_ENV"
fi

get() {  # get <base url> <file> <checksum file>
  curl -fsSL -o "$DIR/$3" "$1/$3"
  curl -fsSL -o "$DIR/$2" "$1/$2"
  ( cd "$DIR" && grep " $2\$" "$3" | sha256sum -c - )
}
get "https://github.com/prometheus/node_exporter/releases/download/v$NV" \
    "node_exporter-$NV.linux-$A.tar.gz" sha256sums.txt
get "https://github.com/inovex/prometheus-libvirt-exporter/releases/download/v$LV" \
    "prometheus-libvirt-exporter-$LV.$A.deb" "prometheus-libvirt-exporter-${LV}_checksums.txt"
echo "ready in $DIR"
