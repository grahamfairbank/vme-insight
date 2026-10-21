#!/usr/bin/env bash
# Install the optional vme-insight exporters on ONE HVM host. Run on the host itself.
#
# From the vme-insight server (served by the "installer" service, see docs/EXPORTERS.md):
#   curl -fsSL http://<vme-insight-host>:8097/install-exporters.sh | sudo bash
#
# Or from a copy of the repo:
#   sudo ./install-exporters.sh [--listen <ip>] [--from <url>] [--libvirt-version <v>]
#
#   --listen <ip>   address both exporters bind to. Default: the address this host
#                   uses to reach the vme-insight server (its management IP).
#   --node-only     install node_exporter only (automatic when the host has no libvirt,
#                   e.g. inside the VME manager VM)
#   --from <url>    vme-insight installer URL to fetch the libvirt exporter package
#                   from (set automatically when the script is served by vme-insight).
#                   Falls back to GitHub if the package isn't there.
#
# What it does:
#   1. node_exporter: the official Prometheus release binary, installed to
#      /usr/local/bin/node_exporter with its own unit, vme-node-exporter.service.
#      (HVM hosts use HPE's apt repositories, which don't carry it, so apt is not used.)
#   2. prometheus-libvirt-exporter (inovex) .deb, installed with dpkg.
#   Both downloads are verified against SHA-256 hashes pinned in this script (or the
#   release checksum files for other versions), and both run as unprivileged dynamic
#   users (the libvirt one with only the libvirt group).
# Neither exporter has authentication: allow 9100 and 9177 only from the vme-insight host.
# Check with your HPE support terms before adding packages to production hypervisors.
set -euo pipefail

# When served by vme-insight, the next line is filled in with the server's address.
FROM="http://{{.Req.Host}}"
[[ "$FROM" == *'{'* ]] && FROM=""   # running from a local copy: placeholder not filled in
LISTEN=""
NODE_ONLY=0
NODE_VERSION="1.12.1"
LIBVIRT_VERSION="2.6.1"
declare -A PINNED=(  # SHA-256 of release files, checked even when downloaded from a mirror
  ["node_exporter-1.12.1.linux-amd64.tar.gz"]="b51d8a76aa2a9156a55d501aca6276fae09e262259a5e4e831d2c2222f084e63"
  ["prometheus-libvirt-exporter-2.6.1.amd64.deb"]="d4562350827794fc1d3d7ded780c95d438d967c37ab7792bcb68af151c50389e"
)

while [[ $# -gt 0 ]]; do
  case "$1" in
    --listen) LISTEN="$2"; shift 2 ;;
    --from) FROM="${2%/}"; shift 2 ;;
    --libvirt-version) LIBVIRT_VERSION="$2"; shift 2 ;;
    --node-version) NODE_VERSION="$2"; shift 2 ;;
    --node-only) NODE_ONLY=1; shift ;;
    -h|--help) sed -n '2,23p' "$0" 2>/dev/null || true; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
[[ $EUID -eq 0 ]] || { echo "run as root (sudo)" >&2; exit 1; }
command -v systemctl >/dev/null && command -v dpkg >/dev/null || { echo "needs a systemd/dpkg host (Ubuntu)" >&2; exit 1; }
ARCH=$(dpkg --print-architecture)
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
say() { printf '\n== %s\n' "$*"; }

# fetch <file> <github release url> <checksum file name>: download from vme-insight's
# mirror (or GitHub) into $TMP and verify its SHA-256
fetch() {
  local file="$1" gh="$2" sums="$3" got want have
  if [[ -n "$FROM" ]] && curl -fsSL -o "$TMP/$file" "$FROM/dist/$file" 2>/dev/null; then
    got="$FROM/dist"
  elif curl -fsSL -o "$TMP/$file" "$gh/$file"; then
    got="$gh"
  else
    echo "could not download $file from ${FROM:+$FROM/dist or }GitHub" >&2; exit 1
  fi
  want="${PINNED[$file]:-}"
  [[ -n "$want" ]] || want=$(curl -fsSL "$got/$sums" | awk -v f="$file" '$2==f{print $1}')
  have=$(sha256sum "$TMP/$file" | awk '{print $1}')
  [[ -n "$want" && "$have" == "$want" ]] || { echo "checksum mismatch for $file (got $have, want ${want:-unknown}); aborting" >&2; exit 1; }
  echo "$file: downloaded from $got, sha256 verified"
}

# ---------------------------------------------------------------- listen address
if [[ -z "$LISTEN" ]]; then
  target=""
  if [[ -n "$FROM" ]]; then
    h=$(sed -E 's#^[a-z]+://##; s#[:/].*$##' <<<"$FROM")
    target=$(getent ahostsv4 "$h" | awk 'NR==1{print $1}')
  fi
  LISTEN=$(ip -4 route get "${target:-1.1.1.1}" 2>/dev/null | sed -nE 's/.* src ([0-9.]+).*/\1/p' | head -1)
  [[ -n "$LISTEN" ]] || { echo "could not work out the management IP; pass --listen <ip>" >&2; exit 1; }
fi
say "host $(hostname), exporters will listen on $LISTEN"

# ---------------------------------------------------------------- node_exporter
say "node_exporter ${NODE_VERSION}"
case "$ARCH" in amd64|arm64) ;; *) echo "unsupported architecture $ARCH" >&2; exit 1 ;; esac
NTAR="node_exporter-${NODE_VERSION}.linux-${ARCH}.tar.gz"
fetch "$NTAR" "https://github.com/prometheus/node_exporter/releases/download/v${NODE_VERSION}" sha256sums.txt
tar -xzf "$TMP/$NTAR" -C "$TMP"
install -m 0755 "$TMP/node_exporter-${NODE_VERSION}.linux-${ARCH}/node_exporter" /usr/local/bin/node_exporter
cat > /etc/systemd/system/vme-node-exporter.service <<UNIT
[Unit]
Description=Prometheus node_exporter for vme-insight
After=network-online.target
Wants=network-online.target

[Service]
DynamicUser=yes
NoNewPrivileges=yes
ProtectSystem=strict
ProtectHome=read-only
ExecStart=/usr/local/bin/node_exporter --web.listen-address=${LISTEN}:9100
Restart=on-failure

[Install]
WantedBy=multi-user.target
UNIT

# no libvirt here (e.g. the VME manager VM): node_exporter only
if [[ $NODE_ONLY -eq 0 ]] && ! getent group libvirt >/dev/null; then
  NODE_ONLY=1
  echo "no libvirt on this host: installing node_exporter only"
fi
SERVICES="vme-node-exporter"
[[ $NODE_ONLY -eq 1 ]] || SERVICES="$SERVICES prometheus-libvirt-exporter"

# ---------------------------------------------------------------- libvirt exporter
if [[ $NODE_ONLY -eq 0 ]]; then
say "libvirt exporter ${LIBVIRT_VERSION}"
DEB="prometheus-libvirt-exporter-${LIBVIRT_VERSION}.${ARCH}.deb"
fetch "$DEB" "https://github.com/inovex/prometheus-libvirt-exporter/releases/download/v${LIBVIRT_VERSION}" \
  "prometheus-libvirt-exporter-${LIBVIRT_VERSION}_checksums.txt"
dpkg -i "$TMP/$DEB" >/dev/null
mkdir -p /etc/systemd/system/prometheus-libvirt-exporter.service.d
cat > /etc/systemd/system/prometheus-libvirt-exporter.service.d/vme-insight.conf <<UNIT
[Service]
# run unprivileged; libvirt group membership is enough to read domain stats
DynamicUser=yes
SupplementaryGroups=libvirt
NoNewPrivileges=yes
ExecStart=
ExecStart=/usr/bin/prometheus-libvirt-exporter --web.listen-address "${LISTEN}:9177"
UNIT
fi

# ---------------------------------------------------------------- start and check
systemctl daemon-reload
systemctl enable -q $SERVICES
systemctl restart $SERVICES
sleep 3
say "checks"
ok=1
for s in $SERVICES; do
  printf '%-30s %s\n' "$s" "$(systemctl is-active "$s" || true)"
  systemctl is-active -q "$s" || ok=0
done
n=$(curl -s "http://$LISTEN:9100/metrics" | grep -c '^node_' || true)
echo "node_* series on :9100:        $n"
if [[ $NODE_ONLY -eq 0 ]]; then
  v=$(curl -s "http://$LISTEN:9177/metrics" | grep -c '^libvirt_domain_info_state' || true)
  echo "VMs seen by libvirt on :9177:  $v"
fi
[[ $ok -eq 1 && $n -gt 0 ]] || { echo "something is not right; see: journalctl -u vme-node-exporter -u prometheus-libvirt-exporter -n 50" >&2; exit 1; }
if command -v ufw >/dev/null && ufw status | grep -q "Status: active"; then
  echo "ufw is active: add one site-approved allow rule for the vme-insight host, e.g."
  echo "  ufw allow from <ip> to any port 9100,9177 proto tcp   (do not disable ufw on HVM hosts)"
fi
echo "Done. vme-insight will start scraping this host within a minute."
