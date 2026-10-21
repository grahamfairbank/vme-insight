"""Discovery helper: dump sample responses from the endpoints the collector uses.

    docker compose run --rm collector python -m vmeinsight.probe

Writes one JSON file per endpoint to /probe (./probe on the host). Useful for
checking field names on a new VME release or when filing an issue. Secrets
(API keys, passwords, tokens) are redacted, but review the files before sharing
them: they contain hostnames, IPs and user names.
"""
import json
import sys
from pathlib import Path

from . import config
from .collect import scrub
from .morpheus import ApiError, Morpheus

ENDPOINTS = [
    ("ping", "/api/ping", None, False),
    ("whoami", "/api/whoami", None, True),
    ("health", "/api/health", None, True),
    ("alarms", "/api/health/alarms", {"max": 25}, True),
    ("zones", "/api/zones", {"max": 25}, True),
    ("clusters", "/api/clusters", {"max": 25}, True),
    ("servers", "/api/servers", {"max": 50}, True),
    ("instances", "/api/instances", {"max": 25}, True),
    ("networks", "/api/networks", {"max": 25}, True),
    ("data-stores", "/api/data-stores", {"max": 25}, True),
    ("activity", "/api/activity", {"max": 25}, True),
]


def main(out="/probe"):
    cfg = config.load()
    api = Morpheus(cfg["morpheus"])
    outdir = Path(out)
    outdir.mkdir(parents=True, exist_ok=True)

    def dump(name, path, params=None, auth=True):
        try:
            j = api.get(path, params, auth=auth)
            (outdir / f"{name}.json").write_text(json.dumps(scrub(j), indent=2, default=str))
            print(f"ok    {path}")
            return j
        except ApiError as e:
            print(f"fail  {path}: {e}")
            return None

    results = {n: dump(n, p, q, a) for n, p, q, a in ENDPOINTS}
    for c in (results.get("clusters") or {}).get("clusters", [])[:5]:
        dump(f"cluster-{c['id']}", f"/api/clusters/{c['id']}")
        dump(f"cluster-{c['id']}-datastores", f"/api/clusters/{c['id']}/datastores")
    for z in (results.get("zones") or {}).get("zones", [])[:5]:
        dump(f"zone-{z['id']}-datastores", f"/api/zones/{z['id']}/data-stores")
    for s in (results.get("servers") or {}).get("servers", [])[:3]:
        dump(f"server-{s['id']}", f"/api/servers/{s['id']}")
    print(f"written to {outdir}")


if __name__ == "__main__":
    main(*sys.argv[1:])
