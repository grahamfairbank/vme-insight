#!/usr/bin/env python3
"""Refresh the documentation screenshots in docs/images from the running stack.

    python3 tools/screenshots.py [--blur TERM ...] [--since ISO-time]

Host names, VM names and their IP addresses (plus every address in the same /24)
are read from the inventory and blurred in the page before each capture. Add
anything else to hide with --blur (e.g. a NAS name used as a datastore name).
The data shown is real; nothing is replaced or made up.
Needs Docker; builds the vme-insight-shots image (headless Chromium) on first run.
"""
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def psql(sql):
    out = subprocess.run(["docker", "compose", "exec", "-T", "timescaledb", "psql", "-U", "vme", "-d", "vme",
                          "-At", "-c", sql], capture_output=True, text=True, cwd=ROOT, check=True).stdout
    return [line for line in out.splitlines() if line.strip()]


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--blur", action="append", default=[], help="extra text to blur (repeatable)")
    ap.add_argument("--since", help="start of the time range (default: first collected sample)")
    a = ap.parse_args()

    env = dict(l.split("=", 1) for l in (ROOT / ".env").read_text().splitlines() if "=" in l and not l.startswith("#"))
    # every server/VM name the stack has ever stored, including deleted ones still in history
    names = psql("""SELECT DISTINCT v FROM (
        SELECT name AS v FROM servers UNION SELECT hostname FROM servers
        UNION SELECT raw->>'externalName' FROM servers UNION SELECT name FROM instances
        UNION SELECT name FROM inventory_changes UNION SELECT resource_name FROM alarms
        UNION SELECT name FROM activity WHERE object_type IN ('Instance', 'Server', 'ComputeServer', 'Host')) x
        WHERE v IS NOT NULL AND length(v) > 2""")
    ips = psql("""SELECT DISTINCT v FROM (SELECT ip_internal AS v FROM servers UNION SELECT ip_external FROM servers
        UNION SELECT split_part(split_part(url, '://', 2), '/', 1) FROM appliance) x WHERE v ~ '^[0-9.]+$'""")
    subnets = sorted({ip.rsplit(".", 1)[0] for ip in ips})
    patterns = [r"\b" + s.replace(".", r"\.") + r"\.\d{1,3}\b" for s in subnets]
    terms = sorted(set(names + a.blur))
    since = a.since or psql("SELECT (extract(epoch FROM min(time)) * 1000)::bigint FROM metrics")[0]
    print(f"blurring {len(terms)} names, {len(subnets)} subnet(s); range {since} to now", file=sys.stderr)

    subprocess.run(["docker", "build", "-q", "-t", "vme-insight-shots", str(ROOT / "tools/screenshots")],
                   check=True, stdout=subprocess.DEVNULL)
    out = ROOT / "docs/images"
    out.mkdir(parents=True, exist_ok=True)
    project = subprocess.run(["docker", "compose", "config", "--format", "json"], capture_output=True, text=True,
                             cwd=ROOT, check=True)
    network = json.loads(project.stdout)["name"] + "_default"
    cmd = ["docker", "run", "--rm", "--shm-size=1g", "--network", network, "--user", f"{__import__('os').getuid()}",
           "-e", f"GF_USER={env.get('GRAFANA_ADMIN_USER', 'admin')}", "-e", "GF_PASSWORD",
           "-e", f"BLUR_TERMS={json.dumps(terms)}", "-e", f"BLUR_PATTERNS={json.dumps(patterns)}",
           "-e", f"T_FROM={since}", "-e", "T_TO=now", "-e", "HOME=/tmp",
           "-v", f"{out}:/out", "-v", f"{ROOT / 'tools/screenshots'}:/work:ro",
           "vme-insight-shots", "python", "/work/shoot.py"]
    r = subprocess.run(cmd, env={**__import__("os").environ, "GF_PASSWORD": env["GRAFANA_ADMIN_PASSWORD"]})
    sys.exit(r.returncode)


if __name__ == "__main__":
    main()
