#!/usr/bin/env bash
# Build the vme-insight appliance: a Debian 13 qcow2 with vme-insight and its container images inside.
#
#   appliance/build.sh [version]        (from the repo root; version defaults to git describe)
#
# Needs Docker and internet access. No /dev/kvm needed (software emulation, slower).
# Output: appliance/build/out/vme-insight-appliance-<version>.qcow2 and SHA256SUMS
set -euo pipefail
cd "$(dirname "$0")/.."
ROOT=$PWD
VERSION=${1:-$(git describe --tags --always --dirty | sed 's/^v//')}
B=$ROOT/appliance/build
STAGE=$B/stage
TREEMAP=2.1.1

echo "== vme-insight appliance $VERSION"
rm -rf "$STAGE" && mkdir -p "$STAGE/vme-insight/appliance/images" "$STAGE/vme-insight/appliance/grafana-plugins" "$B/cache" "$B/out"

echo "== source tree (tracked and new files, nothing git ignores: no .env, config.yaml or certificates)"
git ls-files -z --cached --others --exclude-standard \
  | grep -zv '^appliance/build/' \
  | tar --null -T - -cf - | tar -xf - -C "$STAGE/vme-insight"
rm -rf "$STAGE/vme-insight/probe"

echo "== container images"
# compose refuses to parse without these; the real ones are generated on each VM at first boot
export DB_PASSWORD=x GRAFANA_DB_PASSWORD=x GRAFANA_ADMIN_PASSWORD=x
docker compose build -q collector
IMAGES=$(docker compose --profile https config --images | sort -u)
for img in $IMAGES; do
  docker image inspect "$img" >/dev/null 2>&1 || docker pull -q "$img"
  f=$(echo "$img" | tr '/:' '__').tar.zst
  echo "   $img -> $f"
  docker save "$img" | zstd -q -T0 -12 -o "$STAGE/vme-insight/appliance/images/$f"
done

echo "== Grafana treemap plugin $TREEMAP"
zip=$B/cache/marcusolsson-treemap-panel-$TREEMAP.zip
[ -s "$zip" ] || curl -fsSL -o "$zip" "https://grafana.com/api/plugins/marcusolsson-treemap-panel/versions/$TREEMAP/download"
python3 -c "import sys,zipfile; zipfile.ZipFile(sys.argv[1]).extractall(sys.argv[2])" "$zip" "$STAGE/vme-insight/appliance/grafana-plugins"

echo "== notices"
ver() { echo "$IMAGES" | grep -m1 "$1" | sed 's/.*://'; }
mkdir -p "$STAGE/rootfs" && cp -a appliance/rootfs/. "$STAGE/rootfs/"
sed -i -e "s/@TIMESCALEDB@/$(ver timescaledb)/" -e "s/@GRAFANA@/$(ver grafana)/" -e "s/@GRAFANA_VERSION@/$(ver grafana)/" \
       -e "s/@PROMETHEUS@/$(ver prometheus)/" -e "s/@CADDY@/$(ver caddy)/" -e "s/@TREEMAP@/$TREEMAP/" \
       "$STAGE/rootfs/usr/share/doc/vme-insight-appliance/NOTICE"
echo "$VERSION" > "$STAGE/rootfs/etc/vme-insight/appliance-version"

echo "== disk image (in the builder container)"
docker build -q -t vme-insight-appliance-builder appliance/builder >/dev/null
docker run --rm -v "$B:/build" -v "$ROOT/appliance/builder:/builder:ro" \
  -e VERSION="$VERSION" -e OWNER="$(id -u):$(id -g)" vme-insight-appliance-builder bash /builder/build-image.sh
ls -lh "$B/out"
