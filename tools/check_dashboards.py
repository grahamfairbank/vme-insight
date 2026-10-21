#!/usr/bin/env python3
"""Run every panel query of every provisioned dashboard through Grafana and report errors.

    python3 tools/check_dashboards.py [http://localhost:3000]   (admin creds from .env)

Variables are set to "All"; text boxes use their defaults. Exits non-zero on any error.
"""
import base64
import json
import re
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if "=" in l and not l.startswith("#"))
base = sys.argv[1] if len(sys.argv) > 1 else f"http://localhost:{env.get('GRAFANA_PORT', '3000')}"
auth = base64.b64encode(f"{env.get('GRAFANA_ADMIN_USER', 'admin')}:{env['GRAFANA_ADMIN_PASSWORD']}".encode()).decode()


def interpolate(text, variables, resolved):
    for v in variables:
        name = v["name"]
        if v["type"] == "query" and v.get("allValue") is None:
            vals = resolved.get(name, [])  # "All" expands to every option, as Grafana does
            pipe, csv = "|".join(vals) or "^$", ",".join(vals) or "NULL"
        elif v["type"] == "query":
            pipe = csv = v["allValue"]
        else:
            pipe = csv = str((v.get("current") or {}).get("value", ""))
        text = re.sub(r"\$\{" + name + r":pipe\}", pipe, text)
        text = re.sub(r"\$\{" + name + r"(:[a-z]+)?\}|\$" + name + r"\b", csv, text)
    return text


def resolve(variables):
    """Run expanding query variables in order and keep their values."""
    resolved = {}
    for v in variables:
        if v["type"] != "query" or v.get("allValue") is not None or v["datasource"]["uid"] != "vme-tsdb":
            continue
        q = {"refId": "V", "datasource": v["datasource"], "rawSql": interpolate(v["query"], variables, resolved),
             "format": "table", "rawQuery": True}
        r = post({"queries": [q], "from": "now-6h", "to": "now"})
        frames = (r.get("results") or {}).get("V", {}).get("frames", [])
        vals = []
        for fr in frames:
            names = [f["name"] for f in fr["schema"]["fields"]]
            col = names.index("__value") if "__value" in names else 0
            vals += [str(x) for x in fr["data"]["values"][col]]
        resolved[v["name"]] = vals
    return resolved


def post(body):
    req = urllib.request.Request(f"{base}/api/ds/query", data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "Authorization": f"Basic {auth}"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.loads(e.read() or b"{}") | {"_http": e.code}


def panels(ps):
    for p in ps:
        if p.get("type") == "row":
            yield from panels(p.get("panels", []))
        else:
            yield p


errors = checked = empty = 0
for f in sorted((ROOT / "grafana" / "dashboards").glob("*.json")):
    d = json.loads(f.read_text())
    variables = d.get("templating", {}).get("list", [])
    resolved = resolve(variables)
    for p in panels(d["panels"]):
        for t in p.get("targets", []):
            q = dict(t)
            for k in ("rawSql", "expr"):
                if k in q:
                    q[k] = interpolate(q[k], variables, resolved)
            q.setdefault("datasource", p.get("datasource"))
            q["intervalMs"], q["maxDataPoints"] = 60000, 500
            res = post({"queries": [q], "from": "now-6h", "to": "now"})
            r = (res.get("results") or {}).get(t["refId"], {})
            checked += 1
            err = r.get("error") or res.get("message")
            if err:
                errors += 1
                print(f"ERROR {f.stem} / {p['title']} [{t['refId']}]: {err}")
            elif not any(fr.get("data", {}).get("values") for fr in r.get("frames", [])):
                empty += 1
                print(f"empty {f.stem} / {p['title']} [{t['refId']}]")
print(f"\n{checked} queries, {errors} errors, {empty} returned no data")
sys.exit(1 if errors else 0)
