#!/usr/bin/env bash
# Check a booted appliance.
#
#   appliance/test/check.sh <ssh-private-key>               the QEMU test VM (boot-test.sh), from inside its container
#   appliance/test/check.sh <ssh-private-key> <user@host>   an appliance provisioned in Morpheus (user with sudo)
set -euo pipefail
SSHOPT=(-o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -o ConnectTimeout=120 -o LogLevel=ERROR)
if [ -n "${2:-}" ]; then
  RUN=(ssh -i "$1" "${SSHOPT[@]}" "$2" bash -s)
else
  NAME=vme-insight-appliance-test
  docker cp "$1" "$NAME:/root/id_test" && docker exec "$NAME" chmod 600 /root/id_test
  RUN=(docker exec -i "$NAME" ssh -i /root/id_test -p 2222 "${SSHOPT[@]}" debian@127.0.0.1 bash -s)
fi
"${RUN[@]}" <<'EOF'
set -u
ok() { echo "PASS  $*"; }; bad() { echo "FAIL  $*"; FAILED=1; }; FAILED=0
cd /opt/vme-insight
s=$(cat /run/vme-insight-status 2>/dev/null); case "$s" in running*) ok "status: $s";; *) bad "status: $s";; esac
m=$(sudo run-parts /etc/update-motd.d 2>/dev/null | grep "^vme-insight appliance"); case "$m" in "vme-insight appliance "[0-9]*:*) ok "login banner shows the version: ${m%%:*}";; *) bad "login banner has no version: $m";; esac
for svc in timescaledb collector prometheus grafana; do
  sudo docker compose ps --status running --services </dev/null | grep -qx "$svc" && ok "$svc running" || bad "$svc not running"
done
n=$(sudo docker compose exec -T timescaledb psql -U vme -d vme -tAc "select count(*) from metrics where time > now() - interval '5 minutes'" </dev/null)
[ "${n:-0}" -gt 0 ] && ok "collector wrote $n metric rows in the last 5 minutes" || bad "no recent metrics"
P=$(sudo grep ^GRAFANA_ADMIN_PASSWORD= .env | cut -d= -f2-)
v=$(curl -s -u "admin:$P" http://127.0.0.1:3000/api/plugins/marcusolsson-treemap-panel/settings | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("info",{}).get("version",""), d.get("signature",""))')
[ "$v" = "2.1.1 valid" ] && ok "treemap plugin $v" || bad "treemap plugin: $v"
# sign in the way a browser does: form login, then reuse the session cookie. A cookie marked Secure
# isn't kept by a browser on plain http, which looks like a wrong password (a login loop).
H=$(curl -s -D - -o /dev/null -c /tmp/cj -H 'Content-Type: application/json' -d "{\"user\":\"admin\",\"password\":\"$P\"}" http://127.0.0.1:3000/login)
if sudo grep -q '^GRAFANA_BIND=0.0.0.0' .env && grep -qi '^set-cookie: grafana_session=.*; Secure' <<<"$H"; then
  bad "sign-in cookie is Secure while Grafana is on plain http: browsers loop back to the login page"
else
  [ "$(curl -s -b /tmp/cj -o /dev/null -w %{http_code} http://127.0.0.1:3000/api/user)" = 200 ] && ok "browser-style sign-in works" || bad "browser-style sign-in failed"
fi
rm -f /tmp/cj
d=$(curl -s -u "admin:$P" "http://127.0.0.1:3000/api/search?type=dash-db" | python3 -c 'import sys,json; print(len(json.load(sys.stdin)))')
[ "$d" -ge 9 ] && ok "$d dashboards" || bad "$d dashboards"
sudo docker compose logs grafana </dev/null 2>&1 | grep -q "Installing plugin" && bad "Grafana tried to download plugins" || ok "Grafana downloaded nothing"
sudo docker compose exec -T grafana env </dev/null | grep -qx 'GF_GRAFANA_COM_API_URL=http://127.0.0.1:9/api' && ok "Grafana's grafana.com address points nowhere" || bad "Grafana can still call grafana.com"
want=$(sudo python3 -c 'import yaml; s=yaml.safe_load(open("/etc/vme-insight/appliance.yaml")) or {}; print(s.get("dns_servers") or "", "|", s.get("dns_search") or "")' </dev/null)
if [ "${want%% |*}" ]; then
  have=$(resolvectl dns 2>/dev/null | sed -n 's/^Link [0-9]* ([^)]*): *//p' | grep -v '^$' | sort -u | tr '\n' ' ')
  dom=$(resolvectl domain 2>/dev/null | sed -n 's/^Link [0-9]* ([^)]*): *//p' | grep -v '^$' | sort -u | tr '\n' ' ')
  [ "$have" = "${want%% |*} " ] && [ "$dom" = "${want##*| } " -o -z "${want##*| }" ] && ok "DNS servers from dns_servers: $have(search $dom)" || bad "DNS: want '$want', have servers '$have' search '$dom'"
  getent hosts deb.debian.org >/dev/null && ok "names resolve" || bad "names don't resolve"
fi
[ "$(stat -c '%a' .env config/config.yaml /etc/vme-insight/appliance.yaml | sort -u)" = "600" ] && ok "settings and secrets are mode 600" || bad "secret file modes"
w=$(sudo find /etc /usr /opt/vme-insight -xdev ! -type l \( ! -user root -o -perm -o+w \) ! -path "/usr/share/zoneinfo/*" ! -path "/opt/vme-insight/probe*" | head -3)  # probe/: the collector's own output
[ -z "$w" ] && ok "system files root-owned, none world-writable" || bad "ownership: $w"
sudo /usr/local/sbin/vme-insight-apply >/dev/null 2>&1 && ok "vme-insight-apply runs again cleanly" || bad "re-apply failed"
for u in qemu-guest-agent docker vme-insight-firstboot vme-insight-update-check.timer; do systemctl is-enabled -q "$u" && ok "$u enabled" || bad "$u not enabled"; done
exit $FAILED
EOF
