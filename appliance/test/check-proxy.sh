#!/usr/bin/env bash
# Check proxy use in an appliance booted with  ISOLATED=1 boot-test.sh  (proxy.url: http://10.0.2.100:3128).
# Runs each kind of outbound traffic, then shows what the test proxy saw.
#
#   appliance/test/check-proxy.sh <ssh-private-key>
set -euo pipefail
NAME=vme-insight-appliance-test
docker cp "$1" "$NAME:/root/id_test" && docker exec "$NAME" chmod 600 /root/id_test
docker exec -i "$NAME" ssh -i /root/id_test -p 2222 -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null \
  -o ConnectTimeout=120 -o LogLevel=ERROR debian@127.0.0.1 bash -s <<'EOF' || FAILED=1
set -u
ok() { echo "PASS  $*"; }; bad() { echo "FAIL  $*"; FAILED=1; }; FAILED=0
cd /opt/vme-insight
curl -s -m 10 --noproxy '*' -o /dev/null https://endoflife.date && bad "direct internet works: the test isn't isolated" || ok "no direct internet"
sudo test -s /etc/systemd/system/docker.service.d/vme-insight-proxy.conf && ok "Docker daemon proxy drop-in" || bad "no daemon drop-in"
np=$(sudo python3 -c 'import json; print(json.load(open("/root/.docker/config.json"))["proxies"]["default"]["noProxy"])')
has() { echo "$np" | tr , '\n' | grep -qx "$1"; }
has 10.0.2.101 && has prometheus && has grafana && has .example.internal && ok "no_proxy: Morpheus, the containers and the extra entry" || bad "no_proxy: $np"
sudo docker compose exec -T collector env </dev/null | grep -q '^HTTPS_PROXY=http://10.0.2.100:3128' && ok "collector has HTTPS_PROXY" || bad "collector has no HTTPS_PROXY"
n=$(sudo docker compose exec -T timescaledb psql -U vme -d vme -tAc "select count(*) from metrics where time > now() - interval '5 minutes'" </dev/null)
[ "${n:-0}" -gt 0 ] && ok "Morpheus reached directly: $n metric rows in 5 minutes" || bad "no recent metrics"
P=$(sudo grep ^GRAFANA_ADMIN_PASSWORD= .env | cut -d= -f2-)
uid=$(curl -s -u "admin:$P" http://127.0.0.1:3000/api/datasources | python3 -c 'import sys,json; print([d["uid"] for d in json.load(sys.stdin) if d["type"]=="prometheus"][0])')
curl -s -u "admin:$P" "http://127.0.0.1:3000/api/datasources/uid/$uid/health" | grep -q '"status":"OK"' && ok "Grafana reaches Prometheus directly" || bad "Grafana to Prometheus failed"
sudo vme-insight-update --check >/dev/null 2>&1 && ok "vme-insight-update --check (GitHub) through the proxy" || bad "update check failed"
sudo apt-get -q update >/dev/null 2>&1 && ok "apt update through the proxy" || bad "apt update failed"
sudo docker pull -q busybox:1.36 >/dev/null 2>&1 && ok "docker pull through the proxy" || bad "docker pull failed"
sudo docker rmi -f python:3.12-slim >/dev/null 2>&1; sudo docker pull -q python:3.12-slim >/dev/null 2>&1 && sudo docker compose build -q --no-cache collector </dev/null >/dev/null 2>&1 && ok "collector rebuild as vme-insight-update does it (base image pull, then pip) through the proxy" || bad "collector build failed"
sudo docker compose logs collector </dev/null 2>&1 | grep -qi "endoflife.date.*\(error\|warn\)" && bad "collector: endoflife.date errors" || ok "collector: no endoflife.date errors"
exit $FAILED
EOF
echo "--- destinations the proxy saw:"
docker logs "$NAME" 2>&1 | grep -E '^[0-9:]{8} (CONNECT|GET|POST|error)' | awk '{print $2, $3}' | sed 's/:443$//' | sort | uniq -c
# Grafana must not contact grafana.com while running (update checks, news, Angular patterns, plugin keys).
if docker logs "$NAME" 2>&1 | grep -E '^[0-9:]{8} (CONNECT|GET|POST)' | grep -q 'grafana\.com'; then
  echo "FAIL  something contacted grafana.com through the proxy"; FAILED=1
else
  echo "PASS  nothing contacted grafana.com"
fi
exit "${FAILED:-0}"
