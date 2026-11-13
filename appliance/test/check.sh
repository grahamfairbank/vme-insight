#!/usr/bin/env bash
# Check a booted test appliance (see boot-test.sh). Runs over SSH from inside the test container.
#
#   appliance/test/check.sh <ssh-private-key>
set -euo pipefail
NAME=vme-insight-appliance-test
docker cp "$1" "$NAME:/root/id_test" && docker exec "$NAME" chmod 600 /root/id_test
docker exec -i "$NAME" ssh -i /root/id_test -p 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -o ConnectTimeout=120 -o LogLevel=ERROR debian@127.0.0.1 bash -s <<'EOF'
set -u
ok() { echo "PASS  $*"; }; bad() { echo "FAIL  $*"; FAILED=1; }; FAILED=0
cd /opt/vme-insight
s=$(cat /run/vme-insight-status 2>/dev/null); case "$s" in running*) ok "status: $s";; *) bad "status: $s";; esac
for svc in timescaledb collector prometheus grafana; do
  sudo docker compose ps --status running --services </dev/null | grep -qx "$svc" && ok "$svc running" || bad "$svc not running"
done
n=$(sudo docker compose exec -T timescaledb psql -U vme -d vme -tAc "select count(*) from metrics where time > now() - interval '5 minutes'" </dev/null)
[ "${n:-0}" -gt 0 ] && ok "collector wrote $n metric rows in the last 5 minutes" || bad "no recent metrics"
P=$(sudo grep ^GRAFANA_ADMIN_PASSWORD= .env | cut -d= -f2-)
v=$(curl -s -u "admin:$P" http://127.0.0.1:3000/api/plugins/marcusolsson-treemap-panel/settings | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("info",{}).get("version",""), d.get("signature",""))')
[ "$v" = "2.1.1 valid" ] && ok "treemap plugin $v" || bad "treemap plugin: $v"
d=$(curl -s -u "admin:$P" "http://127.0.0.1:3000/api/search?type=dash-db" | python3 -c 'import sys,json; print(len(json.load(sys.stdin)))')
[ "$d" -ge 9 ] && ok "$d dashboards" || bad "$d dashboards"
sudo docker compose logs grafana </dev/null 2>&1 | grep -q "Installing plugin" && bad "Grafana tried to download plugins" || ok "Grafana downloaded nothing"
[ "$(stat -c '%a' .env config/config.yaml /etc/vme-insight/appliance.yaml | sort -u)" = "600" ] && ok "settings and secrets are mode 600" || bad "secret file modes"
w=$(sudo find /etc /usr /opt/vme-insight -xdev ! -type l \( ! -user root -o -perm -o+w \) ! -path "/usr/share/zoneinfo/*" ! -path "/opt/vme-insight/probe*" | head -3)  # probe/: the collector's own output
[ -z "$w" ] && ok "system files root-owned, none world-writable" || bad "ownership: $w"
sudo /usr/local/sbin/vme-insight-apply >/dev/null 2>&1 && ok "vme-insight-apply runs again cleanly" || bad "re-apply failed"
for u in qemu-guest-agent docker vme-insight-firstboot; do systemctl is-enabled -q "$u" && ok "$u enabled" || bad "$u not enabled"; done
exit $FAILED
EOF
