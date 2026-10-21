#!/usr/bin/env python3
"""Export vme-insight data as CSV, streamed straight from TimescaleDB.

For exports too big for Grafana's Inspect → Download CSV (months of per-minute data,
whole-estate pulls). Run on the vme-insight host, from the repo directory.

Metric samples:
  tools/export_csv.py metrics --kind host --metric cpu_pct --metric mem_pct --since 7d --res 5m -o hosts.csv
  tools/export_csv.py metrics --kind vm --entity web01 --entity web02 --from 2026-10-01 --to 2026-10-15 --res raw
  tools/export_csv.py metrics --kind datastore --since 365d --source hourly     # long-term, from hourly rollups
  tools/export_csv.py metrics --kind host --list-metrics                         # what can be exported

Inventory and events:
  tools/export_csv.py inventory -o inventory.csv      # every host and VM, with OS/agent lifecycle status
  tools/export_csv.py datastores
  tools/export_csv.py changes --since 30d             # inventory change log
  tools/export_csv.py alarms --since 30d
  tools/export_csv.py activity --since 30d

Times are UTC. --res: raw, 1m, 5m, 15m, 1h, 1d (buckets give avg, min, max, samples).
"""
import argparse
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KINDS = ("host", "vm", "cluster", "datastore", "appliance", "summary")
RES = {"raw": None, "1m": "1 minute", "5m": "5 minutes", "15m": "15 minutes", "1h": "1 hour", "1d": "1 day"}

# User input only ever reaches SQL as psql variables (:'name'), which psql quotes safely.
SQL = {
    "metrics_raw": """
        SELECT m.time, m.entity_type AS kind, e.name AS entity, m.entity_id, m.metric, m.value
        FROM metrics m LEFT JOIN entity_names e USING (entity_type, entity_id)
        WHERE m.entity_type = :'kind' AND m.time >= :'t_from' AND m.time < :'t_to'
          AND (:'entities' = '' OR e.name = ANY (string_to_array(:'entities', E'\\x1f')))
          AND (:'metrics' = '' OR m.metric = ANY (string_to_array(:'metrics', E'\\x1f')))
        ORDER BY m.time, entity, m.metric""",
    "metrics_bucket": """
        SELECT time_bucket(:'res'::interval, m.time) AS time, m.entity_type AS kind, e.name AS entity, m.entity_id,
               m.metric, avg(m.value) AS avg, min(m.value) AS min, max(m.value) AS max, count(*) AS samples
        FROM metrics m LEFT JOIN entity_names e USING (entity_type, entity_id)
        WHERE m.entity_type = :'kind' AND m.time >= :'t_from' AND m.time < :'t_to'
          AND (:'entities' = '' OR e.name = ANY (string_to_array(:'entities', E'\\x1f')))
          AND (:'metrics' = '' OR m.metric = ANY (string_to_array(:'metrics', E'\\x1f')))
        GROUP BY 1, 2, 3, 4, 5 ORDER BY 1, 3, 5""",
    "metrics_hourly": """
        SELECT h.bucket AS time, h.entity_type AS kind, e.name AS entity, h.entity_id, h.metric,
               h.avg, h.min, h.max, h.samples
        FROM metrics_hourly h LEFT JOIN entity_names e USING (entity_type, entity_id)
        WHERE h.entity_type = :'kind' AND h.bucket >= :'t_from' AND h.bucket < :'t_to'
          AND (:'entities' = '' OR e.name = ANY (string_to_array(:'entities', E'\\x1f')))
          AND (:'metrics' = '' OR h.metric = ANY (string_to_array(:'metrics', E'\\x1f')))
        ORDER BY 1, 3, 5""",
    "list_metrics": """
        SELECT metric, count(*) AS samples_last_2_days FROM metrics
        WHERE entity_type = :'kind' AND time > now() - INTERVAL '2 days' GROUP BY 1 ORDER BY 1""",
    "inventory": """
        SELECT s.id, s.kind, s.name, s.hostname, sc.cloud, sc.cluster, sc.host, s.power_state, s.status,
               s.ip_internal, s.ip_external, s.max_cores AS vcpu_or_cores, s.max_memory AS memory_bytes,
               s.max_storage AS storage_bytes, s.os_name, s.platform, s.platform_version, s.os_product, s.os_cycle,
               sc.os_status, sc.eol_date, sc.days_to_eol, sc.os_latest, s.agent_installed, s.agent_version,
               sc.agent_status, s.agent_last_update, s.guest_agent_status, s.maintenance, s.member_status,
               s.cpu_model, s.hw_vendor, s.hw_model, s.plan, s.source_image, s.type_code, s.date_created,
               s.first_seen, s.last_seen
        FROM servers s LEFT JOIN server_currency sc ON sc.id = s.id WHERE s.present ORDER BY s.kind, s.name""",
    "datastores": """
        SELECT d.id, d.name, d.type, d.status, cl.name AS cluster, d.capacity_bytes, d.free_bytes,
               d.capacity_bytes - d.free_bytes AS used_bytes,
               round(100.0 * (d.capacity_bytes - d.free_bytes) / NULLIF(d.capacity_bytes, 0), 2) AS used_pct,
               d.raw->>'externalPath' AS host_mount_path, d.first_seen, d.last_seen
        FROM datastores d LEFT JOIN clusters cl ON cl.id = d.cluster_id WHERE d.present ORDER BY d.name""",
    "changes": """
        SELECT time, entity_type AS kind, entity_id, name, field, old_value, new_value FROM inventory_changes
        WHERE time >= :'t_from' AND time < :'t_to' ORDER BY time""",
    "alarms": """
        SELECT start_date, last_seen, severity, name, resource_name, ref_type, ref_id, message, acknowledged, active
        FROM alarms WHERE start_date < :'t_to' AND last_seen >= :'t_from' ORDER BY start_date""",
    "activity": """
        SELECT ts, activity_type, object_type, name, message, user_name, success FROM activity
        WHERE ts >= :'t_from' AND ts < :'t_to' ORDER BY ts""",
}


def when(text, now):
    """'7d', '12h', '30m', '2026-10-01', '2026-10-01T08:00' -> aware UTC datetime."""
    m = re.fullmatch(r"(\d+)([mhdw])", text.strip())
    if m:
        n, u = int(m.group(1)), m.group(2)
        return now - timedelta(**{{"m": "minutes", "h": "hours", "d": "days", "w": "weeks"}[u]: n})
    dt = datetime.fromisoformat(text)
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def run(sql, variables, out):
    """Stream COPY ... TO STDOUT through psql in the timescaledb container."""
    cmd = ["docker", "compose", "exec", "-T", "timescaledb", "psql", "-U", "vme", "-d", "vme",
           "-X", "-q", "-v", "ON_ERROR_STOP=1"]
    for k, v in variables.items():
        cmd += ["-v", f"{k}={v}"]
    body = f"COPY ({sql.strip()}) TO STDOUT WITH (FORMAT csv, HEADER)\n"
    p = subprocess.run(cmd, input=body.encode(), stdout=out, stderr=subprocess.PIPE, cwd=ROOT)
    if p.returncode:
        sys.exit(p.stderr.decode().strip() or f"psql exited with {p.returncode}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("what", choices=("metrics", "inventory", "datastores", "changes", "alarms", "activity"))
    ap.add_argument("--kind", choices=KINDS, default="host", help="metrics: entity type (default host)")
    ap.add_argument("--entity", action="append", default=[], help="metrics: entity name, repeatable (default all)")
    ap.add_argument("--metric", action="append", default=[], help="metrics: metric name, repeatable (default all)")
    ap.add_argument("--list-metrics", action="store_true", help="metrics: list metric names for --kind and exit")
    ap.add_argument("--since", default="24h", help="start relative to now: 30m, 12h, 7d, 4w (default 24h)")
    ap.add_argument("--from", dest="t_from", help="start time (ISO, UTC unless an offset is given); overrides --since")
    ap.add_argument("--to", dest="t_to", help="end time (default now)")
    ap.add_argument("--res", choices=RES, default="5m", help="metrics: resolution (default 5m)")
    ap.add_argument("--source", choices=("raw", "hourly"), default="raw",
                    help="metrics: raw samples, or hourly rollups for ranges beyond raw retention")
    ap.add_argument("-o", "--output", help="write to this file instead of stdout")
    a = ap.parse_args()

    now = datetime.now(timezone.utc)
    t_from = when(a.t_from, now) if a.t_from else when(a.since, now)
    t_to = when(a.t_to, now) if a.t_to else now
    for v in a.entity + a.metric:
        if "\x1f" in v:
            sys.exit("names may not contain the unit separator character")
    variables = {"kind": a.kind, "t_from": t_from.isoformat(), "t_to": t_to.isoformat(),
                 "entities": "\x1f".join(a.entity), "metrics": "\x1f".join(a.metric)}

    if a.what == "metrics":
        if a.list_metrics:
            sql = SQL["list_metrics"]
        elif a.source == "hourly":
            sql = SQL["metrics_hourly"]
        elif RES[a.res] is None:
            sql = SQL["metrics_raw"]
        else:
            sql, variables["res"] = SQL["metrics_bucket"], RES[a.res]
    else:
        sql = SQL[a.what]

    if a.output:
        with open(a.output, "wb") as f:
            run(sql, variables, f)
        lines = sum(1 for _ in open(a.output, "rb")) - 1
        print(f"wrote {max(lines, 0)} rows to {a.output}", file=sys.stderr)
    else:
        sys.stdout.flush()
        run(sql, variables, sys.stdout.buffer)


if __name__ == "__main__":
    main()
