#!/usr/bin/env bash
# Download the exporter packages into installer/dist so HVM hosts install them from the
# vme-insight server instead of GitHub. Run on the vme-insight host.
#   ./tools/fetch-exporter-packages.sh [node_exporter version] [libvirt exporter version] [arch]
set -euo pipefail
NV="${1:-1.12.1}"; LV="${2:-2.6.1}"; A="${3:-amd64}"
DIR="$(cd "$(dirname "$0")/.." && pwd)/installer/dist"; mkdir -p "$DIR"

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
