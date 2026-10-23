#!/usr/bin/env python3
"""Generate the Grafana dashboards in grafana/dashboards/.

Edit this file rather than the JSON, then run:  python3 tools/build_dashboards.py
(Dashboards edited in the Grafana UI can be exported and saved over the JSON too.)
"""
import json
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "grafana" / "dashboards"
DS = {"type": "grafana-postgresql-datasource", "uid": "vme-tsdb"}

# "All" selections are sent as -1, so filters read: (-1 IN ($var) OR col IN ($var))
def f(var, col):
    return f"(-1 IN (${var}) OR {col} IN (${var}))"


# ------------------------------------------------------------------ building blocks
def target(sql, fmt="time_series", ref="A"):
    return {"datasource": DS, "refId": ref, "rawQuery": True, "editorMode": "code",
            "format": fmt, "rawSql": " ".join(sql.split())}


def qvar(name, label, sql, multi=True, include_all=True, hide=0):
    return {
        "type": "query", "name": name, "label": label, "datasource": DS,
        "query": " ".join(sql.split()), "definition": " ".join(sql.split()),
        "refresh": 2, "multi": multi, "includeAll": include_all, "allValue": "-1",
        "current": {"selected": True, "text": ["All"], "value": ["$__all"]} if include_all else {},
        "sort": 1, "hide": hide,
    }


class Board:
    def __init__(self, uid, title, tags=(), refresh="1m", time_from="now-6h", variables=()):
        self.uid, self.title = uid, title
        self.tags = ["vme-insight", *tags]
        self.refresh, self.time_from = refresh, time_from
        self.variables = list(variables)
        self.panels, self.x, self.y, self.rowh, self.nid = [], 0, 0, 0, 1

    def _place(self, w, h):
        if self.x + w > 24:
            self.x, self.y, self.rowh = 0, self.y + self.rowh, 0
        pos = {"x": self.x, "y": self.y, "w": w, "h": h}
        self.x += w
        self.rowh = max(self.rowh, h)
        return pos

    def row(self, title):
        if self.x:
            self.x, self.y, self.rowh = 0, self.y + self.rowh, 0
        self.panels.append({"type": "row", "title": title, "collapsed": False, "id": self.nid,
                            "gridPos": {"x": 0, "y": self.y, "w": 24, "h": 1}, "panels": []})
        self.nid += 1
        self.y += 1

    def add(self, p, w, h, pid=None):
        """Add a panel. pid fixes its id (for panels other tools link to); otherwise ids count up."""
        if pid is None:
            p["id"] = self.nid
            self.nid += 1
        else:
            p["id"] = pid
        p["gridPos"] = self._place(w, h)
        p.setdefault("datasource", DS)
        self.panels.append(p)
        return p

    def json(self):
        return {
            "uid": self.uid, "title": self.title, "tags": self.tags, "editable": True,
            "schemaVersion": 39, "version": 1, "refresh": self.refresh, "graphTooltip": 1,
            "time": {"from": self.time_from, "to": "now"}, "timezone": "browser",
            "templating": {"list": self.variables},
            "links": [{"type": "dashboards", "tags": ["vme-insight"], "asDropdown": True,
                       "title": "VME dashboards", "includeVars": False, "keepTime": True}],
            "panels": self.panels, "annotations": {"list": []},
        }


def stat(title, sql, unit="none", color="blue", thresholds=None, desc="", text=False, link=None, names=False):
    steps = thresholds or [{"color": color, "value": None}]
    p = {
        "type": "stat", "title": title, "description": desc, "targets": [target(sql, "table")],
        "fieldConfig": {"defaults": {"unit": unit, "color": {"mode": "thresholds"},
                                     "thresholds": {"mode": "absolute", "steps": steps}}, "overrides": []},
        "options": {"reduceOptions": {"calcs": ["lastNotNull"], "fields": "/.*/" if text else "", "values": False},
                    "colorMode": "value", "graphMode": "none", "textMode": "value_and_name" if names else "value",
                    "justifyMode": "center", **({"orientation": "horizontal"} if names else {})},
    }
    if link:
        p["links"] = [{"title": title, "url": link}]
    return p


def timeseries(title, sql, unit="none", desc="", legend_calcs=("mean", "max", "lastNotNull"),
               stack=False, minv=None, maxv=None, fill=10, legend="table", bands=None):
    d = {"unit": unit, "color": {"mode": "palette-classic"},
         "custom": {"drawStyle": "line", "lineWidth": 1, "fillOpacity": fill, "showPoints": "never",
                    "spanNulls": 300000, "stacking": {"mode": "normal" if stack else "none"}}}
    if bands:  # shaded green/amber/red zones behind the lines
        d["thresholds"] = {"mode": "absolute", "steps": bands}
        d["custom"]["thresholdsStyle"] = {"mode": "line+area"}
    if minv is not None:
        d["min"] = minv
    if maxv is not None:
        d["max"] = maxv
    return {
        "type": "timeseries", "title": title, "description": desc, "targets": [target(sql)],
        "fieldConfig": {"defaults": d, "overrides": []},
        "options": {"legend": {"displayMode": legend, "placement": "bottom", "calcs": list(legend_calcs),
                               "sortBy": "Mean", "sortDesc": True},
                    "tooltip": {"mode": "multi", "sort": "desc"}},
    }


# CPU ready: VME reports the average per vCPU, in percent. Rule of thumb from vSphere practice.
READY_STEPS = [{"color": "transparent", "value": None}, {"color": "#EAB839", "value": 5}, {"color": "red", "value": 10}]
READY_TILE_STEPS = [{"color": "green", "value": None}, {"color": "#EAB839", "value": 5}, {"color": "red", "value": 10}]
READY_GUIDE = """**CPU ready** is the share of time a VM's vCPUs were ready to run but had to wait for a physical core.
VME reports it per VM as the average across its vCPUs (for a host: across the VMs on it).

| Per vCPU | What it means | What to do |
|---|---|---|
| **under 5%** | Healthy | Nothing |
| **5 to 10%** | Contention: VMs are queuing for CPU | Check the host's CPU usage and vCPU:core ratio; watch the trend |
| **over 10%** | VMs are noticeably slowed | Move VMs to a quieter host, cut vCPUs on oversized VMs, or add capacity |

Look at sustained values: short spikes during backups, patching or boot storms are normal.
Too many vCPUs per physical core raises ready time for every VM on the host, so right-size large VMs first.

VME added this "CPU Ready-equivalent metric" in 9.1.0; HPE doesn't document how it's calculated or a threshold. At low load it reads several times higher than the kernel's
own measurement (*vCPU wait* on the exporter dashboards), so these thresholds err on the side of warning early.
When the two disagree, trust vCPU wait."""

PCT_STEPS = [{"color": "green", "value": None}, {"color": "#EAB839", "value": 75}, {"color": "red", "value": 90}]

# HPE's documentation (authoritative for VME behaviour), branch matching the supported release
HPE_DOCS = "https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/"
HPE_ALARMS = HPE_DOCS + "infrastructure/clusters/hvm/alarms.rst"
HPE_CAPACITY = HPE_DOCS + "infrastructure/clusters/hvm/capacity_planning.rst"
HPE_MONITORING = HPE_DOCS + "infrastructure/clusters/hvm/monitoring.rst"
HPE_REQUIREMENTS = HPE_DOCS + "getting_started/requirements/requirements.rst"
HPE_INSTALLER = HPE_DOCS + "getting_started/installation/singleNode/hpe_installer.rst"
HPE_MAXIMUMS = HPE_DOCS + "infrastructure/clusters/hvm/maximums.rst"


def _steps(amber, red):
    return [{"color": "green", "value": None}, {"color": "#EAB839", "value": amber}, {"color": "red", "value": red}]


def bands_of(steps):
    """Same thresholds as shaded zones behind a graph (no green fill)."""
    return [{"color": "transparent", "value": None}] + steps[1:]


# Colours match VME's built-in HVM alarm defaults, so red here means VME raises an alarm too.
CPU_STEPS = _steps(85, 95)   # Host/VM CPU Usage Warning / Critical
MEM_STEPS = _steps(90, 95)   # Host/VM Memory Usage Warning / Critical
DS_STEPS = _steps(80, 90)    # Datastore Usage Warning / Critical
CAP_STEPS = _steps(70, 85)   # capacity planning: >70% cluster-wide puts N+1 at risk; >85% on one host
ALARM_NOTE = f"\n\nColours match VME's default HVM alarm thresholds ([HVM alarms]({HPE_ALARMS}))."
CPU_DESC = "Amber at 85%, red at 95% (sustained), as VME's Host/VM CPU Usage alarms. Short peaks are normal." + ALARM_NOTE
MEM_DESC = "Amber at 90%, red at 95% (sustained), as VME's Host/VM Memory Usage alarms." + ALARM_NOTE
DS_DESC = ("Amber at 80%, red at 90% used, as VME's Datastore Usage alarms. HPE's monitoring guide treats "
           f"under 15% free as a risk of provisioning failures ([HVM monitoring]({HPE_MONITORING}))." + ALARM_NOTE)
CAP_DESC = ("Cluster memory in use. HPE's capacity planning says to add hosts when memory is above 70% "
            "cluster-wide (N+1 failover at risk) or any single host is above 85% "
            f"([capacity planning]({HPE_CAPACITY})). See the N+1 failover headroom panel.")


def bargauge(title, sql, unit="percent", maxv=100, steps=PCT_STEPS, desc=""):
    d = {"unit": unit, "min": 0, "color": {"mode": "thresholds"},
         "thresholds": {"mode": "absolute", "steps": steps}}
    if maxv is not None:
        d["max"] = maxv
    return {
        "type": "bargauge", "title": title, "description": desc, "targets": [target(sql, "table")],
        "fieldConfig": {"defaults": d, "overrides": []},
        "options": {"orientation": "horizontal", "displayMode": "gradient", "showUnfilled": True,
                    "valueMode": "color", "namePlacement": "left", "sizing": "auto",
                    "reduceOptions": {"values": True, "calcs": ["lastNotNull"], "fields": ""}},
    }


def gauge(title, sql, desc="", steps=PCT_STEPS):
    return {
        "type": "gauge", "title": title, "description": desc, "targets": [target(sql, "table")],
        "fieldConfig": {"defaults": {"unit": "percent", "min": 0, "max": 100, "color": {"mode": "thresholds"},
                                     "thresholds": {"mode": "absolute", "steps": steps}}, "overrides": []},
        "options": {"reduceOptions": {"values": True, "calcs": ["lastNotNull"], "fields": ""},
                    "showThresholdMarkers": True, "showThresholdLabels": False},
    }


def pie(title, sql, desc=""):
    return {
        "type": "piechart", "title": title, "description": desc, "targets": [target(sql, "table")],
        "fieldConfig": {"defaults": {"color": {"mode": "palette-classic"}}, "overrides": []},
        "options": {"pieType": "donut", "displayLabels": [],
                    "legend": {"displayMode": "table", "placement": "right", "values": ["value", "percent"]},
                    "reduceOptions": {"values": True, "calcs": ["lastNotNull"], "fields": ""},
                    "tooltip": {"mode": "single"}},
    }


def colored(field, mapping):
    return {"matcher": {"id": "byName", "options": field}, "properties": [
        {"id": "custom.cellOptions", "value": {"type": "color-background", "mode": "basic"}},
        {"id": "mappings", "value": [{"type": "value", "options": {
            k: {"color": c, "index": i} for i, (k, c) in enumerate(mapping.items())}}]}]}


def unit_override(field, unit):
    return {"matcher": {"id": "byName", "options": field}, "properties": [{"id": "unit", "value": unit}]}


def gauge_cell(field, steps, maxv=100):
    return {"matcher": {"id": "byName", "options": field}, "properties": [
        {"id": "unit", "value": "percent"}, {"id": "min", "value": 0}, {"id": "max", "value": maxv},
        {"id": "thresholds", "value": {"mode": "absolute", "steps": steps}},
        {"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "basic"}}]}


def treemap(title, sql, scheme, desc=""):
    """Rectangles sized by the "share" column, labelled by "VM" (Treemap panel by Grafana Labs)."""
    return {
        "type": "marcusolsson-treemap-panel", "title": title, "description": desc,
        "targets": [target(sql, "table")],
        "fieldConfig": {"defaults": {"unit": "percent", "decimals": 2, "color": {"mode": scheme}}, "overrides": []},
        "options": {"tiling": "treemapSquarify", "textField": "VM", "sizeField": "share", "colorByField": "share",
                    "labelFields": []},
    }


def table(title, sql, overrides=(), desc="", sort=None):
    p = {
        "type": "table", "title": title, "description": desc, "targets": [target(sql, "table")],
        "fieldConfig": {"defaults": {"custom": {"filterable": True, "align": "auto"}},
                        "overrides": list(overrides)},
        "options": {"showHeader": True, "cellHeight": "sm", "footer": {"show": False}},
    }
    if sort:
        p["options"]["sortBy"] = [{"displayName": sort[0], "desc": sort[1]}]
    return p


STATUS_COLORS = {"current": "green", "update available": "#EAB839", "eol < 180d": "orange",
                 "end of life": "red", "outdated": "orange", "not installed": "red",
                 "unknown": "gray", "unknown os": "gray", "unknown release": "gray"}
POWER_COLORS = {"on": "green", "off": "gray", "unknown": "#EAB839", "suspended": "#EAB839"}


# series of one metric for one entity type, filtered by variables
def series(entity, metric, name_expr="s.name", join="servers s ON s.id = m.entity_id", where="", agg="avg"):
    return f"""
      SELECT $__timeGroupAlias(m.time, $__interval), {name_expr} AS metric, {agg}(m.value) AS value
      FROM metrics m JOIN {join}
      WHERE $__timeFilter(m.time) AND m.entity_type = '{entity}' AND m.metric = '{metric}' {where}
      GROUP BY 1, 2 ORDER BY 1"""


def latest_metric(entity, metric, name_expr="s.name", join="servers s ON s.id = m.entity_id", where="",
                  limit=None, order="DESC", window="15 minutes"):
    lim = f"LIMIT {limit}" if limit else ""
    return f"""
      SELECT {name_expr} AS name, last(m.value, m.time) AS value
      FROM metrics m JOIN {join}
      WHERE m.time > now() - INTERVAL '{window}' AND m.entity_type = '{entity}' AND m.metric = '{metric}' {where}
      GROUP BY 1 ORDER BY 2 {order} {lim}"""


MGR_DISK_STEPS = [{"color": "green", "value": None}, {"color": "#EAB839", "value": 75}, {"color": "red", "value": 85}]
MGR_DISK_BANDS = [{"color": "transparent", "value": None}, {"color": "#EAB839", "value": 75}, {"color": "red", "value": 85}]
MGR_DISK_GUIDE = f"""The VME manager stores its database (MySQL), OpenSearch/Elasticsearch data (logs and stats),
RabbitMQ queues, uploaded images and local backups on its disk, mostly under `/var/opt/morpheus`.

| Used | Meaning |
|---|---|
| **under 75%** | Healthy |
| **75 to 85%** | Plan: find what's growing (usually `elasticsearch`, `bitcan/backups` or `morpheus-ui/vms`) |
| **over 85%** | Act now. HPE: with the partition 85% full or more, Elasticsearch enters an unhealthy state and the appliance won't function properly ([requirements]({HPE_REQUIREMENTS})). |

To free space: lower **Stats Retainment** (Administration > Settings > Appliance) or the log **Availability Time Frame**
(Administration > Settings > Monitoring), move backups to a Storage Provider, or grow the manager's disk. HPE doesn't publish a disk size for the VM Essentials manager; it comes with the QCOW2 image the manager is deployed from."""

# days until a manager filesystem is full, from the last 7 days of free-space samples
def mgr_days_to_full(path_sql):
    # needs a day of samples: a trend from a few hours is noise, not a forecast
    return f"""(SELECT CASE WHEN regr_slope(m.value, extract(epoch FROM m.time)) < 0
                  AND max(m.time) - min(m.time) >= INTERVAL '1 day'
                  THEN (array_agg(m.value ORDER BY m.time DESC))[1] / -regr_slope(m.value, extract(epoch FROM m.time)) / 86400 END
                FROM metrics m WHERE m.entity_type = 'appliance' AND m.metric = 'storage.fs.' || {path_sql} || '.available'
                  AND m.time > now() - INTERVAL '7 days')"""


MGR_FS_SQL = f"""
    SELECT f->>'path' AS "Mount", f->>'name' AS "Device", (f->>'total')::bigint AS "Size",
           (f->>'used')::bigint AS "Used", (f->>'available')::bigint AS "Free", (f->>'percent')::numeric AS "Used %",
           {mgr_days_to_full("(f->>'path')")} AS "Days to full"
    FROM appliance a, jsonb_array_elements(a.health->'storage'->'files') f WHERE a.id = 1 ORDER BY 6 DESC"""

# N+1: if the largest host fails, can the rest hold every running VM's memory? Each host keeps 4 GiB for itself.
N1_CTE = """
    WITH h AS (SELECT cluster_id, id, max_memory - 4294967296 AS usable FROM servers
               WHERE kind = 'host' AND present AND cluster_id IS NOT NULL),
         c AS (SELECT cluster_id, count(*) AS hosts, sum(usable) AS usable, sum(usable) - max(usable) AS n1 FROM h GROUP BY 1),
         v AS (SELECT h.cluster_id, sum(vm.max_memory) AS alloc FROM servers vm JOIN h ON h.id = vm.host_id
               WHERE vm.kind = 'vm' AND vm.present AND vm.power_state = 'on' GROUP BY 1)"""
N1_SQL = N1_CTE + """
    SELECT cl.name, 100.0 * COALESCE(v.alloc, 0) / NULLIF(c.n1, 0) AS pct
    FROM c JOIN clusters cl ON cl.id = c.cluster_id LEFT JOIN v USING (cluster_id) {where} ORDER BY 2 DESC"""
N1_TABLE_SQL = N1_CTE + """
    SELECT cl.name AS "Cluster", c.hosts AS "Hosts", c.usable AS "Usable memory", c.n1 AS "Usable if largest host fails",
           COALESCE(v.alloc, 0) AS "Allocated to running VMs", c.n1 - COALESCE(v.alloc, 0) AS "Headroom",
           100.0 * COALESCE(v.alloc, 0) / NULLIF(c.n1, 0) AS "% of N+1 capacity"
    FROM c JOIN clusters cl ON cl.id = c.cluster_id LEFT JOIN v USING (cluster_id) ORDER BY 7 DESC"""
N1_DESC = f"""Memory allocated to running VMs, as a share of what the cluster could still hold if its largest host failed.
Each host keeps 4 GB for itself (OS, cluster services, agent, libvirt). VME treats VM memory as a reservation
(no memory overcommit by default), so **over 100% means a host failure or maintenance evacuation can't place every VM**.
HPE's rule: never allocate more than (N-1)/N of cluster memory, e.g. keep 33% free on 3 hosts
([capacity planning]({HPE_CAPACITY}))."""

MGR_SIZING_DESC = f"""How this manager compares with both HPE sizing guides, each with its own result.

**VM Essentials** (applies to a VME manager): the HPE Morpheus Manager Installer and `hvmcli deploy` create the manager
from the VME QCOW2 image with a sizing profile: **Small = 12 GB RAM, 2 vCPUs**; **Medium** (the `hvmcli` default) and
**Large** are bigger, but HPE doesn't publish their values or a manager disk size ([installer]({HPE_INSTALLER})).
HPE publishes no per-manager object limits and asks for a workload-specific sizing review before large deployments
([maximums]({HPE_MAXIMUMS})).

**Morpheus Enterprise** (for reference, e.g. before moving to an Enterprise licence): the appliance requirements are
**16 GB RAM, 4 cores, 200 GB disk** ([requirements]({HPE_REQUIREMENTS})).

Memory allows 1 GB for what the OS doesn't report. Sustained CPU pressure, high JVM memory or swap use on this
dashboard are the signs to move up a profile."""
MGR_SIZING_SQL = """
    WITH m AS (SELECT DISTINCT ON (metric) metric, value FROM metrics
               WHERE entity_type = 'appliance' AND metric IN ('cpu.processorCount', 'memory.systemMemory', 'storage.total')
                 AND time > now() - INTERVAL '1 hour' ORDER BY metric, time DESC),
         c AS (SELECT (SELECT value FROM m WHERE metric = 'cpu.processorCount') AS cores,
                      (SELECT value FROM m WHERE metric = 'memory.systemMemory') AS mem,
                      (SELECT value FROM m WHERE metric = 'storage.total') AS disk)
    SELECT r.resource AS "Item", r.have AS "Manager has",
           r.ess AS "Essentials needs", r.ess_res AS "Essentials result",
           r.ent AS "Enterprise needs", r.ent_res AS "Enterprise result"
    FROM (SELECT 1 AS o, 'Overall' AS resource, cores::int || ' vCPUs, ' || pg_size_pretty(mem::bigint) AS have,
                 'Small profile: 2 vCPUs, 12 GB' AS ess,
                 CASE WHEN cores < 2 OR mem < 11 * 2^30 THEN 'below Small'
                      WHEN cores <= 2 AND mem < 13 * 2^30 THEN 'matches Small'
                      ELSE 'Medium or Large' END AS ess_res,
                 '4 cores, 16 GB, 200 GB' AS ent,
                 CASE WHEN cores >= 4 AND mem >= 15 * 2^30 AND disk >= 200e9 THEN 'meets' ELSE 'below' END AS ent_res FROM c
          UNION ALL SELECT 2, 'CPU cores', cores::int::text, '2',
                 CASE WHEN cores >= 2 THEN 'meets' ELSE 'below' END, '4',
                 CASE WHEN cores >= 4 THEN 'meets' ELSE 'below' END FROM c WHERE cores IS NOT NULL
          UNION ALL SELECT 3, 'Memory', pg_size_pretty(mem::bigint), '12 GB',
                 CASE WHEN mem >= 11 * 2^30 THEN 'meets' ELSE 'below' END, '16 GB',
                 CASE WHEN mem >= 15 * 2^30 THEN 'meets' ELSE 'below' END FROM c WHERE mem IS NOT NULL
          UNION ALL SELECT 4, 'Disk', pg_size_pretty(disk::bigint), 'not published', 'n/a', '200 GB',
                 CASE WHEN disk >= 200e9 THEN 'meets' ELSE 'below' END FROM c WHERE disk IS NOT NULL
         ) r ORDER BY r.o"""

SERVICES_SQL = """
    SELECT initcap(k) AS "Service", COALESCE(a.health -> k ->> 'status', 'n/a') AS "Status"
    FROM appliance a, unnest(ARRAY['database', 'elastic', 'rabbit', 'cpu', 'memory', 'storage']) AS k
    WHERE a.id = 1"""

# Idle VM: running, and VME's CPU figure never above IDLE_PCT for the whole IDLE_WINDOW.
# VME reports about 2% CPU even for a VM the kernel measures at under 1%, so 1% would never match.
IDLE_PCT = 5
IDLE_WINDOW = "24 hours"
IDLE_DESC = (f"Running VMs whose CPU never went above {IDLE_PCT}% in the last {IDLE_WINDOW} (VME's CPU figure, "
             "sampled every minute). VME's figure reads about 2% even for an idle VM, so the threshold sits above that. "
             "Candidates to power off, shrink or reclaim; check the list on the VME Virtual "
             f"Machines dashboard first. Change IDLE_PCT / IDLE_WINDOW in tools/build_dashboards.py to redefine idle.")


def idle_vms_sql(where, select):
    return f"""
        WITH w AS (SELECT m.entity_id, max(m.value) AS peak, avg(m.value) AS mean, count(*) AS samples
                   FROM metrics m JOIN servers s ON s.id = m.entity_id
                   WHERE m.entity_type = 'vm' AND m.metric = 'cpu_pct' AND m.time > now() - INTERVAL '{IDLE_WINDOW}'
                     AND s.present AND s.power_state = 'on' {where}
                   GROUP BY 1 HAVING count(*) >= 10)
        {select}"""


# Resource weight: each VM's current usage as a share of the cluster's capacity (latest VME sample).
WEIGHT_HOSTS = "s.kind = 'host' AND s.present AND (-1 IN ($cluster) OR s.cluster_id IN ($cluster))"
WEIGHT_VMS = "v.kind = 'vm' AND v.present AND (-1 IN ($cluster) OR v.cluster_id IN ($cluster))"
WEIGHT_CPU_SQL = f"""
    WITH cap AS (SELECT sum(s.max_cores)::float AS total FROM servers s WHERE {WEIGHT_HOSTS})
    SELECT v.name || ' · ' || to_char(100.0 * (v.raw->'stats'->>'cpuUsage')::float / 100.0 * v.max_cores / NULLIF(cap.total, 0), 'FM990.00') || '%' AS "VM",
           100.0 * (v.raw->'stats'->>'cpuUsage')::float / 100.0 * v.max_cores / NULLIF(cap.total, 0) AS share
    FROM servers v, cap WHERE {WEIGHT_VMS} AND v.power_state = 'on' AND (v.raw->'stats'->>'cpuUsage')::float > 0
    ORDER BY 2 DESC"""
WEIGHT_MEM_SQL = f"""
    WITH cap AS (SELECT sum(s.max_memory)::float AS total FROM servers s WHERE {WEIGHT_HOSTS})
    SELECT v.name || ' · ' || to_char(100.0 * v.max_memory::float / NULLIF(cap.total, 0), 'FM990.00') || '%' AS "VM",
           100.0 * v.max_memory::float / NULLIF(cap.total, 0) AS share
    FROM servers v, cap WHERE {WEIGHT_VMS} AND v.power_state = 'on' AND v.max_memory > 0
    ORDER BY 2 DESC"""
WEIGHT_DISK_SQL = f"""
    WITH used_ds AS (SELECT DISTINCT (vol->'datastore'->>'id')::bigint AS id
                     FROM servers v, jsonb_array_elements(v.raw->'volumes') vol WHERE {WEIGHT_VMS}),
         cap AS (SELECT sum(d.capacity_bytes)::float AS total FROM datastores d JOIN used_ds USING (id) WHERE d.present)
    SELECT v.name || ' · ' || to_char(100.0 * (v.raw->'stats'->>'usedStorage')::float / NULLIF(cap.total, 0), 'FM990.00') || '%' AS "VM",
           100.0 * (v.raw->'stats'->>'usedStorage')::float / NULLIF(cap.total, 0) AS share
    FROM servers v, cap WHERE {WEIGHT_VMS} AND (v.raw->'stats'->>'usedStorage')::float > 0
    ORDER BY 2 DESC"""
WEIGHT_DESC = ("Each rectangle is a VM, sized and coloured by its share of the cluster's {what}. "
               "Spot the few VMs that dominate a resource at a glance. Uses VME's latest sample. {detail} "
               "Very small VMs can be too thin to see; hover for values, or use the VME Data Export dashboard.")


CLUSTER_VAR = qvar("cluster", "Cluster", "SELECT name AS __text, id AS __value FROM clusters WHERE present ORDER BY name")
HOST_VAR = qvar("host", "Host", f"""SELECT name AS __text, id AS __value FROM servers
    WHERE kind = 'host' AND present AND {f('cluster', 'cluster_id')} ORDER BY name""")
VM_VAR = qvar("vm", "VM", f"""SELECT name AS __text, id AS __value FROM servers
    WHERE kind = 'vm' AND present AND {f('cluster', 'cluster_id')} AND {f('host', 'host_id')} ORDER BY name""")
# Same picker, but "All" expands to the real ids so they can also filter Prometheus (vme_host_id label)
HOST_VAR_EXPANDED = dict(HOST_VAR, allValue=None)
TOPN_VAR = {"type": "custom", "name": "topn", "label": "Top N", "query": "5,10,20,50",
            "current": {"text": "10", "value": "10"},
            "options": [{"text": v, "value": v, "selected": v == "10"} for v in ("5", "10", "20", "50")]}

HOST_F = f"AND {f('cluster', 's.cluster_id')} AND {f('host', 's.id')}"
VM_F = f"AND {f('cluster', 's.cluster_id')} AND {f('host', 's.host_id')}"
VM_ONLY_F = VM_F + f" AND {f('vm', 's.id')}"


# ------------------------------------------------------------------ tiles shared with the widget board
def estate_tiles():
    """Estate count tiles (VME Overview, Estate row). Fresh dicts on every call."""
    cnt = "SELECT count(*) FROM servers s WHERE present AND kind = '{k}' {extra} " + f"AND {f('cluster', 's.cluster_id')}"
    return {
        "clusters": stat("Clusters", f"SELECT count(*) FROM clusters c WHERE present AND {f('cluster', 'c.id')}"),
        "hosts": stat("Hosts", cnt.format(k="host", extra="")),
        "vms": stat("VMs", cnt.format(k="vm", extra="")),
        "vms_running": stat("VMs running", cnt.format(k="vm", extra="AND power_state = 'on'"), color="green"),
        "vms_stopped": stat("VMs stopped", cnt.format(k="vm", extra="AND power_state <> 'on'"), color="text"),
        "datastores": stat("Datastores", "SELECT count(*) FROM datastores WHERE present"),
        "alarms": stat("Active alarms", "SELECT count(*) FROM alarms WHERE active AND present",
                       thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}]),
        "manager": stat("VME manager", "SELECT build_version AS version FROM appliance", text=True, color="text"),
    }


def contention_tiles():
    """CPU ready tiles (VME Overview, CPU contention row). Fresh dicts on every call."""
    vmw = VM_F
    ready_now = lambda metric, agg: f"""
        SELECT {agg} FROM (SELECT last(m.value, m.time) AS v FROM metrics m JOIN servers s ON s.id = m.entity_id
          WHERE m.time > now() - INTERVAL '15 minutes' AND m.entity_type = 'vm' AND m.metric = '{metric}' {vmw}
          GROUP BY m.entity_id) x"""
    return {
        "worst_vm_ready": stat("Worst VM CPU ready", ready_now("cpu_ready_pct", "max(v)"), "percent", thresholds=READY_TILE_STEPS,
                               desc=READY_GUIDE + "\n\nThis tile: the highest per-VM average right now."),
        "worst_vcpu_ready": stat("Worst single vCPU ready", ready_now("cpu_ready_max_vcpu_pct", "max(v)"), "percent", thresholds=READY_TILE_STEPS,
                                 desc=READY_GUIDE + "\n\nThis tile: the most-starved individual vCPU of any VM. One busy vCPU can hide inside a VM's average."),
        "vms_ready_5_10": stat("VMs at 5 to 10% ready", ready_now("cpu_ready_pct", "count(*) FILTER (WHERE v >= 5 AND v < 10)"),
                               thresholds=[{"color": "green", "value": None}, {"color": "#EAB839", "value": 1}],
                               desc=READY_GUIDE + "\n\nThis tile: running VMs in the contention band."),
        "vms_ready_over_10": stat("VMs over 10% ready", ready_now("cpu_ready_pct", "count(*) FILTER (WHERE v >= 10)"),
                                  thresholds=[{"color": "green", "value": None}, {"color": "red", "value": 1}],
                                  desc=READY_GUIDE + "\n\nThis tile: running VMs that are noticeably slowed."),
    }


# Panel ids of the widget board are a contract with embedders such as the vme-insight VME plugin:
# never renumber or reuse them. Add new tiles with new ids.
WIDGET_TILES = [  # (panel id, tile key, width)
    (1, "clusters", 3), (2, "hosts", 3), (3, "vms", 3), (4, "vms_running", 3),
    (5, "vms_stopped", 3), (6, "datastores", 3), (7, "alarms", 3), (8, "manager", 3),
    (9, "worst_vm_ready", 6), (10, "worst_vcpu_ready", 6), (11, "vms_ready_5_10", 6), (12, "vms_ready_over_10", 6),
]


def widget_board():
    """Single tiles for embedding (Grafana /d-solo/vme-widget?panelId=N), with ids that never change."""
    hidden = lambda v: {**v, "hide": 2}
    b = Board("vme-widget", "VME Summary tiles (for embedding)", ["embed"],
              variables=[hidden(CLUSTER_VAR), hidden(HOST_VAR)])
    tiles = {**estate_tiles(), **contention_tiles()}
    for pid, key, w in WIDGET_TILES:
        b.add(tiles[key], w, 4, pid=pid)
    b.nid = max(pid for pid, _, _ in WIDGET_TILES) + 1
    return b


# ------------------------------------------------------------------ overview
def overview():
    b = Board("vme-overview", "VME Overview", ["overview"], variables=[CLUSTER_VAR, HOST_VAR, TOPN_VAR])
    b.row("Estate")
    t = estate_tiles()
    for name in ("clusters", "hosts", "vms", "vms_running", "vms_stopped", "datastores", "alarms", "manager"):
        b.add(t[name], 3, 4)

    b.row("Cluster capacity")
    cl = "clusters c ON c.id = m.entity_id"
    clf = f"AND {f('cluster', 'c.id')}"
    b.add(gauge("Cluster CPU", latest_metric("cluster", "cpu_pct", "c.name", cl, clf), CPU_DESC, CPU_STEPS), 8, 6)
    b.add(gauge("Cluster memory", latest_metric("cluster", "mem_pct", "c.name", cl, clf), CAP_DESC, CAP_STEPS), 8, 6)
    b.add(gauge("Cluster storage", latest_metric("cluster", "storage_pct", "c.name", cl, clf),
                desc="Host-reported storage (sum over hosts). See Datastores for shared storage."), 8, 6)
    b.add(timeseries("Cluster CPU usage", series("cluster", "cpu_pct", "c.name", cl, clf), "percent", minv=0,
                     desc=CPU_DESC, bands=bands_of(CPU_STEPS)), 12, 8)
    b.add(timeseries("Cluster memory usage (add hosts above 70%)", series("cluster", "mem_pct", "c.name", cl, clf), "percent",
                     minv=0, desc=CAP_DESC, bands=bands_of(CAP_STEPS)), 12, 8)
    b.add(bargauge("N+1 failover headroom: VM memory vs capacity left if a host fails", N1_SQL.format(where=""),
                   maxv=150, steps=[{"color": "green", "value": None}, {"color": "#EAB839", "value": 90}, {"color": "red", "value": 100}],
                   desc=N1_DESC), 24, 5)

    b.row("Hosts")
    b.add(timeseries("Host CPU usage", series("host", "cpu_pct", where=HOST_F), "percent", minv=0,
                     desc=CPU_DESC, bands=bands_of(CPU_STEPS)), 12, 9)
    b.add(timeseries("Host memory usage", series("host", "mem_pct", where=HOST_F), "percent", minv=0,
                     desc=MEM_DESC, bands=bands_of(MEM_STEPS)), 12, 9)
    b.add(bargauge("Running VMs per host", latest_metric("host", "vm_running", where=HOST_F),
                   unit="none", maxv=None, steps=[{"color": "blue", "value": None}]), 8, 8)
    b.add(timeseries("Host network receive", series("host", "net_rx", where=HOST_F), "Bps"), 8, 8)
    b.add(timeseries("Host network transmit", series("host", "net_tx", where=HOST_F), "Bps"), 8, 8)

    b.row("Datastores")
    b.add(bargauge("Datastore usage (amber 80%, red 90%)", """SELECT name, 100.0 * (capacity_bytes - free_bytes) / NULLIF(capacity_bytes, 0) AS used
        FROM datastores WHERE present AND capacity_bytes > 0 ORDER BY used DESC""", steps=DS_STEPS, desc=DS_DESC), 12, 8)
    b.add(timeseries("Datastore free space", series("datastore", "free_bytes", "d.name", "datastores d ON d.id = m.entity_id"),
                     "bytes", minv=0), 12, 8)

    b.add(table("Datastores", """
        SELECT name AS "Datastore", type AS "Type", status AS "Status", capacity_bytes AS "Size",
               capacity_bytes - free_bytes AS "Used", free_bytes AS "Free",
               100.0 * (capacity_bytes - free_bytes) / NULLIF(capacity_bytes, 0) AS "Used %"
        FROM datastores WHERE present ORDER BY 7 DESC NULLS LAST""",
        [unit_override("Size", "bytes"), unit_override("Used", "bytes"), unit_override("Free", "bytes"),
         colored("Status", {"provisioned": "green", "online": "green", "warning": "orange", "failed": "red", "offline": "red"}),
         {"matcher": {"id": "byName", "options": "Used %"}, "properties": [
             {"id": "unit", "value": "percent"}, {"id": "max", "value": 100}, {"id": "min", "value": 0},
             {"id": "thresholds", "value": {"mode": "absolute", "steps": DS_STEPS}},
             {"id": "custom.cellOptions", "value": {"type": "gauge", "mode": "basic"}}]}]), 24, 7)

    b.row("VME manager")
    am = lambda m: f"""SELECT value FROM metrics WHERE entity_type = 'appliance' AND metric = '{m}'
                       AND time > now() - INTERVAL '30 minutes' ORDER BY time DESC LIMIT 1"""
    b.add(stat("Manager CPU", am("cpu.cpuTotalLoad"), "percent", thresholds=CPU_STEPS), 4, 4)
    b.add(stat("JVM memory", am("memory.memoryPercent"), "percent", thresholds=MEM_STEPS,
               desc="Heap used by the VME application (Java)."), 4, 4)
    b.add(stat("System memory", am("memory.systemMemoryPercent"), "percent", thresholds=MEM_STEPS,
               desc="Memory used in the manager VM, including the database and OpenSearch/Elasticsearch."), 4, 4)
    b.add(stat("Manager disk used (amber 75%, red 85%)", f"""SELECT max((f->>'percent')::numeric) FROM appliance a,
        jsonb_array_elements(a.health->'storage'->'files') f WHERE a.id = 1""", "percent", thresholds=MGR_DISK_STEPS,
               desc=MGR_DISK_GUIDE + "\n\nThis tile: the fullest filesystem on the manager. Details on the Manager & Collector dashboard.",
               link="/d/vme-health"), 4, 4)
    b.add(table("Manager services", SERVICES_SQL, [colored("Status", {"ok": "green", "warning": "orange", "error": "red"})]), 8, 4)
    b.add(table("Clouds", """SELECT name AS "Cloud", type_name AS "Type", status AS "Status", last_sync AS "Last sync"
        FROM clouds WHERE present ORDER BY name""", [colored("Status", {"ok": "green", "syncing": "blue", "error": "red"})]), 10, 6)
    b.add(table("Recent activity", """SELECT ts AS "Time", activity_type AS "Type", name AS "Object",
        message AS "Message", user_name AS "User" FROM activity ORDER BY ts DESC LIMIT 50"""), 14, 6)

    b.row("CPU contention")
    vmw = VM_F
    t = contention_tiles()
    for name in ("worst_vm_ready", "worst_vcpu_ready", "vms_ready_5_10", "vms_ready_over_10"):
        b.add(t[name], 6, 4)

    b.row("VM resource weight")
    b.add(treemap("VME CPU weight", WEIGHT_CPU_SQL, "continuous-blues", WEIGHT_DESC.format(
        what="CPU", detail="Share = the VM's CPU usage × its vCPUs, divided by the cores of all hosts. Running VMs only.")), 8, 9)
    b.add(treemap("VME memory weight (allocated)", WEIGHT_MEM_SQL, "continuous-YlRd", WEIGHT_DESC.format(
        what="memory", detail="Share = the memory allocated to the VM divided by the memory of all hosts. VME reserves a "
                              "VM's full allocation (no memory overcommit by default), so allocation is what it takes "
                              "from the cluster; VME's in-guest usage figure is unreliable without a guest agent. "
                              "Running VMs only.")), 8, 9)
    b.add(treemap("VME disk weight", WEIGHT_DISK_SQL, "continuous-purples", WEIGHT_DESC.format(
        what="storage", detail="Share = the VM's disk space in use divided by the capacity of the datastores its disks are "
                               "on. Includes stopped VMs, which still occupy storage.")), 8, 9)

    b.row("Top VMs")
    b.add(bargauge("Top VMs by CPU", latest_metric("vm", "cpu_pct", where=vmw, limit="$topn"), steps=CPU_STEPS, desc=CPU_DESC), 8, 10)
    b.add(bargauge("Top VMs by memory", latest_metric("vm", "mem_pct", where=vmw, limit="$topn"), steps=MEM_STEPS, desc=MEM_DESC), 8, 10)
    b.add(bargauge("Top VMs by CPU ready (healthy < 5%)", latest_metric("vm", "cpu_ready_pct", where=vmw, limit="$topn"),
                   maxv=20, steps=READY_TILE_STEPS, desc=READY_GUIDE), 8, 10)
    b.add(timeseries("Top VMs CPU over time", f"""
        WITH top AS (SELECT m.entity_id FROM metrics m JOIN servers s ON s.id = m.entity_id
                     WHERE $__timeFilter(m.time) AND m.entity_type = 'vm' AND m.metric = 'cpu_pct' {vmw}
                     GROUP BY 1 ORDER BY avg(m.value) DESC LIMIT $topn)
        SELECT $__timeGroupAlias(m.time, $__interval), s.name AS metric, avg(m.value) AS value
        FROM metrics m JOIN top USING (entity_id) JOIN servers s ON s.id = m.entity_id
        WHERE $__timeFilter(m.time) AND m.entity_type = 'vm' AND m.metric = 'cpu_pct'
        GROUP BY 1, 2 ORDER BY 1""", "percent", minv=0), 12, 9)
    b.add(timeseries("Top VMs network (rx + tx)", f"""
        WITH top AS (SELECT m.entity_id FROM metrics m JOIN servers s ON s.id = m.entity_id
                     WHERE $__timeFilter(m.time) AND m.entity_type = 'vm' AND m.metric IN ('net_rx', 'net_tx') {vmw}
                     GROUP BY 1 ORDER BY avg(m.value) DESC LIMIT $topn)
        SELECT $__timeGroupAlias(m.time, $__interval), s.name AS metric, sum(m.value) / count(DISTINCT m.time) AS value
        FROM metrics m JOIN top USING (entity_id) JOIN servers s ON s.id = m.entity_id
        WHERE $__timeFilter(m.time) AND m.entity_type = 'vm' AND m.metric IN ('net_rx', 'net_tx')
        GROUP BY 1, 2 ORDER BY 1""", "Bps"), 12, 9)

    b.row("Fleet")
    b.add(stat("VM disk size (provisioned)", f"""
        SELECT percentile_cont(0.5) WITHIN GROUP (ORDER BY s.max_storage) AS "Median", avg(s.max_storage) AS "Average"
        FROM servers s WHERE s.kind = 'vm' AND s.present AND s.max_storage > 0 {VM_F}""", "bytes", names=True,
        desc="Median and average disk space provisioned per VM (all disks of all current VMs, running or not). "
             "A median well below the average means a few very large VMs."), 8, 5)
    b.add(stat(f"Idle VMs (CPU never above {IDLE_PCT}% in {IDLE_WINDOW})",
               idle_vms_sql(VM_F, f"SELECT count(*) FILTER (WHERE peak < {IDLE_PCT}) FROM w"),
               thresholds=[{"color": "green", "value": None}, {"color": "#EAB839", "value": 1}], desc=IDLE_DESC,
               link="/d/vme-vms"), 8, 5)
    b.add(stat("Running VMs assessed", idle_vms_sql(VM_F, "SELECT count(*) FROM w"), color="text",
               desc=f"Running VMs with at least 10 CPU samples in the last {IDLE_WINDOW}, the base for the idle count."), 8, 5)
    b.add(timeseries("VMs running vs stopped", """
        SELECT $__timeGroupAlias(time, $__interval), CASE metric WHEN 'vms_on' THEN 'running' ELSE 'stopped' END AS metric,
               max(value) AS value
        FROM metrics WHERE $__timeFilter(time) AND entity_type = 'summary' AND metric IN ('vms_on', 'vms_off')
        GROUP BY 1, 2 ORDER BY 1""", "none", stack=True, fill=40, legend="list", legend_calcs=("lastNotNull",)), 12, 8)
    b.add(pie("VM power state", f"""SELECT COALESCE(power_state, 'unknown') AS state, count(*) FROM servers s
        WHERE present AND kind = 'vm' {VM_F} GROUP BY 1 ORDER BY 2 DESC"""), 6, 8)
    b.add(pie("VM OS families", f"""SELECT COALESCE(os_product, 'unknown') AS os, count(*) FROM servers s
        WHERE present AND kind = 'vm' {VM_F} GROUP BY 1 ORDER BY 2 DESC"""), 6, 8)
    return b


# ------------------------------------------------------------------ hosts
def hosts():
    b = Board("vme-hosts", "VME Hosts", ["hosts"], variables=[CLUSTER_VAR, HOST_VAR_EXPANDED])
    b.row("Host inventory")
    b.add(table("Hosts", f"""
        SELECT s.name AS "Host", cl.name AS "Cluster", s.power_state AS "Power", s.status AS "Status",
               s.ip_internal AS "IP", s.os_name AS "OS", s.platform_version AS "Version",
               s.max_cores AS "Cores", s.max_memory AS "Memory",
               (SELECT count(*) FROM servers v WHERE v.host_id = s.id AND v.present AND v.kind = 'vm') AS "VMs",
               (SELECT count(*) FROM servers v WHERE v.host_id = s.id AND v.present AND v.kind = 'vm' AND v.power_state = 'on') AS "Running",
               s.agent_version AS "Agent", s.agent_last_update AS "Agent check-in",
               EXTRACT(epoch FROM now() - s.agent_last_update)::int AS "Agent age",
               s.member_status AS "Cluster member", s.maintenance AS "Maintenance",
               s.cpu_model AS "CPU model", s.hw_vendor || ' ' || s.hw_model AS "Hardware"
        FROM servers s LEFT JOIN clusters cl ON cl.id = s.cluster_id
        WHERE s.kind = 'host' AND s.present {HOST_F} ORDER BY 1""",
        [unit_override("Memory", "bytes"), colored("Power", POWER_COLORS),
         colored("Cluster member", {"online": "green", "offline": "red"}),
         colored("Maintenance", {"true": "orange", "false": "transparent"}),
         {"matcher": {"id": "byName", "options": "Agent age"}, "properties": [
             {"id": "unit", "value": "s"},
             {"id": "thresholds", "value": {"mode": "absolute", "steps": _steps(120, 300)}},
             {"id": "custom.cellOptions", "value": {"type": "color-text"}}]}],
        desc="Agent age: time since the host's Morpheus agent last reported. HPE: healthy within 2 minutes; "
             f"over 5 minutes VME raises Host Unreachable ([HVM monitoring]({HPE_MONITORING})). "
             "The value is as of the last collection, so it can read up to a minute high."), 24, 7)
    b.row("CPU and memory")
    b.add(timeseries("CPU usage", series("host", "cpu_pct", where=HOST_F), "percent", minv=0,
                     desc=CPU_DESC, bands=bands_of(CPU_STEPS)), 12, 8)
    b.add(timeseries("Memory usage", series("host", "mem_pct", where=HOST_F), "percent", minv=0, maxv=100,
                     desc=MEM_DESC, bands=bands_of(MEM_STEPS)), 12, 8)
    b.add(timeseries("Memory used", series("host", "mem_used_bytes", where=HOST_F), "bytes", minv=0), 12, 8)
    b.add(timeseries("CPU ready (healthy < 5%, act > 10%)", series("host", "cpu_ready_pct", where=HOST_F), "percent",
                     minv=0, desc=READY_GUIDE, bands=READY_STEPS), 12, 8)
    b.add(timeseries("Swap used", series("host", "swap_used_bytes", where=HOST_F), "bytes", minv=0), 12, 8)
    b.row("Storage and network")
    b.add(timeseries("Network receive", series("host", "net_rx", where=HOST_F), "Bps"), 12, 8)
    b.add(timeseries("Network transmit", series("host", "net_tx", where=HOST_F), "Bps"), 12, 8)
    b.row("Local filesystems")
    b.add(table("Host local storage (reported by VME)", f"""
        SELECT s.name AS "Host", (s.raw->'stats'->>'maxStorage')::bigint AS "Size",
               (s.raw->'stats'->>'usedStorage')::bigint AS "Used",
               (s.raw->'stats'->>'maxStorage')::bigint - (s.raw->'stats'->>'usedStorage')::bigint AS "Free",
               100.0 * (s.raw->'stats'->>'usedStorage')::numeric / NULLIF((s.raw->'stats'->>'maxStorage')::numeric, 0) AS "Used %"
        FROM servers s WHERE s.kind = 'host' AND s.present {HOST_F} ORDER BY 5 DESC NULLS LAST""",
        [unit_override("Size", "bytes"), unit_override("Used", "bytes"), unit_override("Free", "bytes"), gauge_cell("Used %", FS_STEPS)],
        desc="VME reports one total per host for its local disks. Per-mount detail (below) needs node_exporter on the host."), 10, 7)
    b.add(timeseries("Host local storage used % (reported by VME)", series("host", "storage_pct", where=HOST_F), "percent",
                     minv=0, maxv=100, bands=FS_BANDS), 14, 7)
    fs_panels(b, 'vme_host_id=~"${host:pipe}"')
    b.row("Failover capacity (N+1)")
    b.add(table("N+1 failover capacity per cluster", N1_TABLE_SQL,
        [unit_override(c, "bytes") for c in ("Usable memory", "Usable if largest host fails", "Allocated to running VMs", "Headroom")]
        + [gauge_cell("% of N+1 capacity", [{"color": "green", "value": None}, {"color": "#EAB839", "value": 90},
                                            {"color": "red", "value": 100}], maxv=150)], desc=N1_DESC), 24, 5)

    b.row("Workload")
    b.add(timeseries("Running VMs", series("host", "vm_running", where=HOST_F), "none", minv=0), 12, 8)
    b.add(bargauge("vCPU : core ratio (running VMs)", f"""
        SELECT s.name, sum(v.max_cores)::float / NULLIF(s.max_cores, 0) AS ratio
        FROM servers s JOIN servers v ON v.host_id = s.id AND v.present AND v.kind = 'vm' AND v.power_state = 'on'
        WHERE s.kind = 'host' AND s.present {HOST_F} GROUP BY s.name, s.max_cores ORDER BY 2 DESC""",
        unit="none", maxv=None, steps=[{"color": "green", "value": None}, {"color": "#EAB839", "value": 4},
                                       {"color": "red", "value": 8}],
        desc="vCPUs of running VMs on the host divided by the host's cores. HPE's guidance: 1:1 for latency-sensitive "
             "workloads, 2:1 general purpose, 4:1 dev/test, 8:1 or more only for idle or bursty workloads. Over-committed "
             f"CPU means more scheduling latency (CPU ready), not failures ([capacity planning]({HPE_CAPACITY}))."), 12, 8)
    return b


# ------------------------------------------------------------------ VMs
def vms():
    b = Board("vme-vms", "VME Virtual Machines", ["vms"], variables=[CLUSTER_VAR, HOST_VAR, VM_VAR])
    b.row("Performance")
    b.add(timeseries("CPU usage", series("vm", "cpu_pct", where=VM_ONLY_F), "percent", minv=0,
                     desc=CPU_DESC, bands=bands_of(CPU_STEPS)), 12, 9)
    b.add(timeseries("Memory usage", series("vm", "mem_pct", where=VM_ONLY_F), "percent", minv=0, maxv=100,
                     desc=MEM_DESC, bands=bands_of(MEM_STEPS)), 12, 9)
    b.add(timeseries("Disk usage", series("vm", "storage_pct", where=VM_ONLY_F), "percent", minv=0, maxv=100), 8, 8)
    b.add(timeseries("Network receive", series("vm", "net_rx", where=VM_ONLY_F), "Bps"), 8, 8)
    b.add(timeseries("Network transmit", series("vm", "net_tx", where=VM_ONLY_F), "Bps"), 8, 8)
    b.add(timeseries("Disk IOPS", series("vm", "disk_iops", where=VM_ONLY_F), "iops"), 8, 8)
    b.add(timeseries("CPU ready (healthy < 5%, act > 10%)", series("vm", "cpu_ready_pct", where=VM_ONLY_F), "percent",
                     minv=0, desc=READY_GUIDE, bands=READY_STEPS), 8, 8)
    b.add(timeseries("Powered on", series("vm", "up", where=VM_ONLY_F, agg="min"), "none", minv=0, maxv=1,
                     legend="list", legend_calcs=("min",), fill=0), 8, 8)
    b.add(timeseries("Worst single vCPU ready (healthy < 5%)", series("vm", "cpu_ready_max_vcpu_pct", where=VM_ONLY_F),
                     "percent", minv=0, bands=READY_STEPS,
                     desc=READY_GUIDE + "\n\nThis panel: the most-starved vCPU of each VM. Compare with the average to spot one overloaded vCPU."), 24, 8)
    b.row("Idle VM candidates")
    b.add(table(f"Running VMs by peak CPU (idle = never above {IDLE_PCT}% in {IDLE_WINDOW})",
        idle_vms_sql(VM_ONLY_F, f"""SELECT s.name AS "VM", h.name AS "Host", s.max_cores AS "vCPU", s.max_memory AS "Memory",
               w.peak AS "Peak CPU", w.mean AS "Average CPU", w.peak < {IDLE_PCT} AS "Idle"
        FROM w JOIN servers s ON s.id = w.entity_id LEFT JOIN servers h ON h.id = s.host_id ORDER BY w.peak"""),
        [unit_override("Memory", "bytes"), unit_override("Peak CPU", "percent"), unit_override("Average CPU", "percent"),
         colored("Idle", {"true": "#EAB839", "false": "transparent"})], desc=IDLE_DESC), 24, 6)

    b.row("Details")
    b.add(table("Virtual machines", f"""
        SELECT s.name AS "VM", s.power_state AS "Power", s.status AS "Status", h.name AS "Host", cl.name AS "Cluster",
               s.ip_internal AS "IP", s.max_cores AS "vCPU", s.max_memory AS "Memory", s.max_storage AS "Disk",
               s.os_name AS "OS", s.guest_agent_status AS "Guest agent", s.agent_version AS "Morpheus agent",
               cd.name AS "Cloud", s.plan AS "Plan", s.source_image AS "Image", i.owner AS "Owner",
               s.date_created AS "Created"
        FROM servers s LEFT JOIN servers h ON h.id = s.host_id LEFT JOIN clusters cl ON cl.id = s.cluster_id
        LEFT JOIN instances i ON s.id = ANY(i.server_ids) AND i.present LEFT JOIN clouds cd ON cd.id = s.cloud_id
        WHERE s.kind = 'vm' AND s.present {VM_ONLY_F} ORDER BY 1""",
        [unit_override("Memory", "bytes"), unit_override("Disk", "bytes"), colored("Power", POWER_COLORS),
         colored("Guest agent", {"connected": "green", "disconnected": "orange", "unknown": "gray"})]), 24, 10)
    return b


# ------------------------------------------------------------------ inventory & lifecycle
def lifecycle_board():
    b = Board("vme-lifecycle", "VME Inventory & Lifecycle", ["inventory", "lifecycle"], refresh="5m",
              time_from="now-30d", variables=[CLUSTER_VAR])
    sc = f"FROM server_currency sc WHERE {f('cluster', 'sc.cluster_id')}"
    red = [{"color": "green", "value": None}, {"color": "red", "value": 1}]
    amber = [{"color": "green", "value": None}, {"color": "orange", "value": 1}]
    b.row("Summary")
    b.add(stat("Servers tracked", f"SELECT count(*) {sc}"), 4, 4)
    b.add(stat("OS end of life", f"SELECT count(*) {sc} AND os_status = 'end of life'", thresholds=red), 4, 4)
    b.add(stat("OS EOL < 180 days", f"SELECT count(*) {sc} AND os_status = 'eol < 180d'", thresholds=amber), 4, 4)
    b.add(stat("OS updates available", f"SELECT count(*) {sc} AND os_status = 'update available'", thresholds=amber,
               desc="Point release behind the latest for its cycle (as reported by the agent/guest tools)."), 4, 4)
    b.add(stat("Agent outdated", f"SELECT count(*) {sc} AND agent_status = 'outdated'", thresholds=amber), 4, 4)
    b.add(stat("Agent not installed", f"SELECT count(*) {sc} AND agent_status = 'not installed'", thresholds=amber), 4, 4)
    b.add(stat("VM guest agent down", f"SELECT count(*) {sc} AND kind = 'vm' AND guest_agent_status IS DISTINCT FROM 'connected' AND power_state = 'on'",
               thresholds=amber, desc="Running VMs whose QEMU guest agent is not connected. OS details and clean shutdown need it."), 4, 4)
    b.row("Distribution")
    b.add(pie("OS status", f"SELECT os_status, count(*) {sc} GROUP BY 1 ORDER BY 2 DESC"), 6, 8)
    b.add(pie("OS release", f"SELECT COALESCE(os_product || ' ' || os_cycle, os_name, 'unknown') AS os, count(*) {sc} GROUP BY 1 ORDER BY 2 DESC"), 6, 8)
    b.add(pie("Agent version", f"SELECT COALESCE(agent_version, 'none') AS agent, count(*) {sc} GROUP BY 1 ORDER BY 2 DESC"), 6, 8)
    b.add(stat("Target agent version", "SELECT version FROM agent_target", text=True, color="text",
               desc="lifecycle.expected_agent_version in config.yaml, or the newest version seen in the fleet."), 6, 4)
    b.add(stat("VME manager version", "SELECT build_version AS version FROM appliance", text=True, color="text"), 6, 4)
    b.row("Servers")
    b.add(table("OS and agent currency", f"""
        SELECT name AS "Name", kind AS "Kind", cluster AS "Cluster", host AS "Host", power_state AS "Power",
               COALESCE(os_name, os_product) AS "OS", os_version_full AS "Version", os_latest AS "Latest in cycle",
               os_status AS "OS status", eol_date AS "EOL", days_to_eol AS "Days to EOL",
               agent_version AS "Morpheus agent", agent_status AS "Agent status", agent_last_update AS "Agent check-in",
               guest_agent_status AS "Guest agent"
        {sc} ORDER BY CASE os_status WHEN 'end of life' THEN 0 WHEN 'eol < 180d' THEN 1 WHEN 'update available' THEN 2
                                     ELSE 3 END, days_to_eol NULLS LAST, name""",
        [colored("OS status", STATUS_COLORS), colored("Agent status", STATUS_COLORS), colored("Power", POWER_COLORS),
         colored("Guest agent", {"connected": "green", "disconnected": "orange", "unknown": "gray"})]), 24, 12)
    b.add(table("OS releases in use", """
        SELECT s.os_product AS "Product", s.os_cycle AS "Cycle", count(*) AS "Servers", l.release_date AS "Released",
               l.support_date AS "Active support ends", l.eol_date AS "EOL", l.latest AS "Latest", l.lts AS "LTS"
        FROM servers s LEFT JOIN os_lifecycle l ON l.product = s.os_product AND lower(l.cycle) = lower(s.os_cycle)
        WHERE s.present AND s.os_product IS NOT NULL
        GROUP BY 1, 2, 4, 5, 6, 7, 8 ORDER BY 6 NULLS LAST""",
        desc="Lifecycle data from endoflife.date, refreshed daily."), 12, 8)
    b.add(table("Unrecognised OS strings", """
        SELECT COALESCE(os_name, '') AS "OS name", COALESCE(platform, '') AS "Platform",
               COALESCE(platform_version, '') AS "Platform version", count(*) AS "Servers"
        FROM servers WHERE present AND (os_product IS NULL OR os_cycle IS NULL) GROUP BY 1, 2, 3 ORDER BY 4 DESC""",
        desc="Add lifecycle.os_rules in config.yaml to map these."), 12, 8)
    b.row("Changes")
    b.add(table("Inventory changes", """
        SELECT time AS "Time", entity_type AS "Kind", name AS "Name", field AS "Field",
               old_value AS "Old", new_value AS "New"
        FROM inventory_changes WHERE $__timeFilter(time) ORDER BY time DESC LIMIT 500"""), 24, 10)
    return b


# ------------------------------------------------------------------ manager & collector health
def health():
    b = Board("vme-health", "VME Manager & Collector", ["health"], variables=[])
    b.row("Alarms")
    b.add(table("Alarms", """
        SELECT start_date AS "Started", severity AS "Severity", name AS "Alarm", resource_name AS "Resource",
               message AS "Message", acknowledged AS "Ack", active AS "Active"
        FROM alarms WHERE present AND (active OR last_seen > now() - INTERVAL '7 days') ORDER BY active DESC, start_date DESC""",
        [colored("Severity", {"error": "red", "critical": "red", "warning": "orange", "info": "blue"})]), 24, 8)
    b.add(timeseries("Active alarms", """
        SELECT $__timeGroupAlias(time, $__interval), metric, max(value) AS value FROM metrics
        WHERE $__timeFilter(time) AND entity_type = 'summary' AND metric IN ('alarms_active', 'alarms_unacknowledged')
        GROUP BY 1, 2 ORDER BY 1""", "none", minv=0, legend="list", legend_calcs=("lastNotNull",)), 24, 7)
    b.row("Manager resources")
    am = lambda m: f"""SELECT value FROM metrics WHERE entity_type = 'appliance' AND metric = '{m}'
                       AND time > now() - INTERVAL '30 minutes' ORDER BY time DESC LIMIT 1"""
    b.add(stat("Disk used (amber 75%, red 85%)", """SELECT max((f->>'percent')::numeric) FROM appliance a,
        jsonb_array_elements(a.health->'storage'->'files') f WHERE a.id = 1""", "percent", thresholds=MGR_DISK_STEPS,
               desc=MGR_DISK_GUIDE), 4, 4)
    b.add(stat("Disk free", """SELECT min((f->>'available')::bigint) FROM appliance a,
        jsonb_array_elements(a.health->'storage'->'files') f WHERE a.id = 1""", "bytes",
               thresholds=[{"color": "red", "value": None}, {"color": "#EAB839", "value": 10e9}, {"color": "green", "value": 25e9}],
               desc="Free space on the fullest manager filesystem. " + MGR_DISK_GUIDE), 4, 4)
    b.add(stat("Days until disk full", f"""SELECT min({mgr_days_to_full("(f->>'path')")}) FROM appliance a,
        jsonb_array_elements(a.health->'storage'->'files') f WHERE a.id = 1""", "d",
               thresholds=[{"color": "red", "value": None}, {"color": "#EAB839", "value": 30}, {"color": "green", "value": 90}],
               desc="At the growth rate of the last 7 days. Blank until there's a day of history, or while usage isn't growing."), 4, 4)
    b.add(stat("System memory", am("memory.systemMemoryPercent"), "percent", thresholds=MEM_STEPS,
               desc="Memory used in the manager VM, including the database and OpenSearch/Elasticsearch. Some cache is normal."), 4, 4)
    b.add(stat("JVM memory", am("memory.memoryPercent"), "percent", thresholds=MEM_STEPS,
               desc="Heap used by the VME application (Java)."), 4, 4)
    b.add(stat("Swap used", am("memory.systemUsedSwap"), "bytes",
               thresholds=[{"color": "green", "value": None}, {"color": "#EAB839", "value": 512e6}, {"color": "red", "value": 2e9}],
               desc="Steady or growing swap use on the manager means it needs more memory."), 4, 4)
    b.add(table("Manager filesystems (reported by VME)", MGR_FS_SQL,
        [unit_override("Size", "bytes"), unit_override("Used", "bytes"), unit_override("Free", "bytes"),
         unit_override("Days to full", "d"), gauge_cell("Used %", MGR_DISK_STEPS)], desc=MGR_DISK_GUIDE), 24, 5)
    result_colors = {"meets": "green", "below": "orange", "below Small": "orange", "matches Small": "blue",
                     "Medium or Large": "blue", "n/a": "transparent"}
    sizing = table("Manager size: Essentials and Enterprise", MGR_SIZING_SQL,
        [colored("Essentials result", result_colors), colored("Enterprise result", result_colors)], desc=MGR_SIZING_DESC)
    sizing["fieldConfig"]["defaults"]["custom"]["filterable"] = False  # four fixed rows: filters only cost header space
    b.add(sizing, 24, 6)
    b.add(timeseries("Manager disk used % (amber 75, red 85)", f"""
        SELECT $__timeGroupAlias(time, $__interval), substr(metric, 12, length(metric) - 19) AS metric, avg(value) AS value
        FROM metrics WHERE $__timeFilter(time) AND entity_type = 'appliance' AND metric LIKE 'storage.fs.%.percent'
        GROUP BY 1, 2 ORDER BY 1""", "percent", minv=0, maxv=100, legend="list", bands=MGR_DISK_BANDS, desc=MGR_DISK_GUIDE), 24, 6)

    b.row("Manager")
    b.add(table("Services", SERVICES_SQL, [colored("Status", {"ok": "green", "warning": "orange", "error": "red"})]), 6, 7)
    amts = lambda metrics, legend_sql="metric": f"""
        SELECT $__timeGroupAlias(time, $__interval), {legend_sql} AS metric, avg(value) AS value FROM metrics
        WHERE $__timeFilter(time) AND entity_type = 'appliance' AND metric IN ({", ".join(f"'{m}'" for m in metrics)})
        GROUP BY 1, 2 ORDER BY 1"""
    b.add(timeseries("Manager CPU and memory", amts(["cpu.cpuTotalLoad", "memory.memoryPercent", "memory.systemMemoryPercent"],
        "CASE metric WHEN 'cpu.cpuTotalLoad' THEN 'CPU' WHEN 'memory.memoryPercent' THEN 'JVM memory' ELSE 'system memory' END"),
        "percent", minv=0, maxv=100, legend="list"), 18, 7)
    b.add(timeseries("Database connections", amts(["database.usedConnections", "database.maxUsedConnections", "database.busyConnections"],
        "substr(metric, 10)"), "none", minv=0, legend="list"), 8, 7)
    b.add(timeseries("RabbitMQ", amts(["rabbit.queued_messages", "rabbit.busy_queues", "rabbit.error_queues"], "substr(metric, 8)"),
        "none", minv=0, legend="list", desc="Messages waiting across manager queues. A growing backlog means the manager is falling behind."), 8, 7)
    b.add(timeseries("Elasticsearch", f"""
        SELECT $__timeGroupAlias(time, $__interval), substr(metric, 9) AS metric, avg(value) AS value FROM metrics
        WHERE $__timeFilter(time) AND entity_type = 'appliance' AND metric LIKE 'elastic.%Percent'
        GROUP BY 1, 2 ORDER BY 1""", "percent", minv=0, maxv=100, legend="list"), 8, 7)
    b.add(timeseries("All manager metrics (regex)", """
        SELECT $__timeGroupAlias(time, $__interval), metric, avg(value) AS value FROM metrics
        WHERE $__timeFilter(time) AND entity_type = 'appliance' AND metric ~* '${appliance_metric:raw}'
        GROUP BY 1, 2 ORDER BY 1""", "none",
        desc="Every metric collected from /api/health. Narrow with the regex box at the top."), 24, 8)
    b.variables.append({"type": "textbox", "name": "appliance_metric", "label": "Manager metric regex",
                        "query": "cpu|memory", "current": {"text": "cpu|memory", "value": "cpu|memory"}})
    b.row("Manager VM detail (node_exporter, optional)")
    msel = 'job="vme-manager"'
    b.add(ptime("Manager CPU % (node_exporter)", pq(host_cpu(msel), "CPU"), "percent", minv=0, maxv=100,
                desc="Needs node_exporter inside the manager VM: run the exporter installer there (see docs/EXPORTERS.md)."), 8, 7)
    b.add(ptime("Manager memory used %", pq(host_mem(msel), "memory"), "percent", minv=0, maxv=100), 8, 7)
    b.add(ptime("Manager pressure (PSI)", [
        pq(f'100 * rate(node_pressure_cpu_waiting_seconds_total{{{msel}}}[$__rate_interval])', "cpu"),
        pq(f'100 * rate(node_pressure_memory_waiting_seconds_total{{{msel}}}[$__rate_interval])', "memory", "B"),
        pq(f'100 * rate(node_pressure_io_waiting_seconds_total{{{msel}}}[$__rate_interval])', "io", "C")], "percent", minv=0,
        desc="Share of time work waited for CPU, memory or disk. Sustained I/O pressure slows the database and Elasticsearch."), 8, 7)
    fs_panels(b, msel)
    b.add(ptime("Manager disk latency", [
        pq(f'sum(rate(node_disk_read_time_seconds_total{{{msel}, {DISK}}}[$__rate_interval])) / sum(rate(node_disk_reads_completed_total{{{msel}, {DISK}}}[$__rate_interval]))', "read"),
        pq(f'sum(rate(node_disk_write_time_seconds_total{{{msel}, {DISK}}}[$__rate_interval])) / sum(rate(node_disk_writes_completed_total{{{msel}, {DISK}}}[$__rate_interval]))', "write", "B")],
        "s", minv=0, desc="Write latency above ~20 ms slows the manager's database."), 24, 7)

    b.row("Collector")
    b.add(table("Last run per task", """
        SELECT DISTINCT ON (task) task AS "Task", time AS "Last run", ok AS "OK", duration_ms AS "ms",
               items AS "Items", error AS "Error"
        FROM collector_runs ORDER BY task, time DESC""",
        [colored("OK", {"true": "green", "false": "red"})]), 12, 7)
    b.add(timeseries("Task duration", """
        SELECT $__timeGroupAlias(time, $__interval), task AS metric, avg(duration_ms) AS value FROM collector_runs
        WHERE $__timeFilter(time) GROUP BY 1, 2 ORDER BY 1""", "ms", minv=0), 12, 7)
    b.add(table("Recent errors", """
        SELECT time AS "Time", task AS "Task", error AS "Error" FROM collector_runs
        WHERE NOT ok AND $__timeFilter(time) ORDER BY time DESC LIMIT 50"""), 24, 6)
    b.add(table("Database size", """
        SELECT 'metrics (raw)' AS "Table", pg_size_pretty(hypertable_size('metrics')) AS "Size",
               (SELECT count(*) FROM timescaledb_information.chunks WHERE hypertable_name = 'metrics') AS "Chunks"
        UNION ALL SELECT 'database total', pg_size_pretty(pg_database_size(current_database())), NULL"""), 12, 5)
    return b


# ================================================================== exporter (Prometheus) dashboards
PROM = {"type": "prometheus", "uid": "vme-prom"}
# job=~"hvm-.*": HVM hosts only (the VME manager has its own job, vme-manager)
HOSTSEL = 'job=~"hvm-.*", source=~"$source", cluster=~"$cluster", nodename=~"$host"'
VMSEL = HOSTSEL + ', domain=~"$domain"'
DISK = 'device!~"dm-.*|sr.*|md.*|loop.*|ram.*|nbd.*|zram.*"'
NIC = 'device!~"lo|vnet.*|veth.*|tap.*|virbr.*|docker.*|br-.*|ovs.*|genev_sys.*|vxlan.*|vme.*"'


def pq(expr, legend="", ref="A", instant=False, fmt="time_series"):
    return {"datasource": PROM, "refId": ref, "expr": " ".join(expr.split()), "legendFormat": legend,
            "instant": instant, "range": not instant, "format": fmt, "editorMode": "code"}


def pvar(name, label, query, include_all=True, multi=True):
    return {"type": "query", "name": name, "label": label, "datasource": PROM,
            "query": {"query": query, "refId": name, "qryType": 1}, "definition": query,
            "refresh": 2, "multi": multi, "includeAll": include_all, "allValue": ".*", "sort": 1,
            "current": {"selected": True, "text": ["All"], "value": ["$__all"]} if include_all else {}}


PROM_VARS = [
    pvar("source", "Estate", 'label_values(node_uname_info{job="hvm-node"}, source)'),
    pvar("cluster", "Cluster", 'label_values(node_uname_info{job="hvm-node", source=~"$source"}, cluster)'),
    pvar("host", "Host", 'label_values(node_uname_info{job="hvm-node", source=~"$source", cluster=~"$cluster"}, nodename)'),
    pvar("domain", "VM", 'label_values(libvirt_domain_info_state{source=~"$source", cluster=~"$cluster", nodename=~"$host"}, domain)'),
]


def ptime(title, targets, unit="none", desc="", minv=None, maxv=None, stack=False, legend="table", bands=None):
    p = timeseries(title, "SELECT 1", unit, desc, minv=minv, maxv=maxv, stack=stack, legend=legend, bands=bands)
    p["datasource"] = PROM
    p["targets"] = targets if isinstance(targets, list) else [targets]
    return p


def pbar(title, expr, legend, unit="percent", maxv=100, steps=PCT_STEPS, desc=""):
    p = bargauge(title, "SELECT 1", unit, maxv, steps, desc)
    p["datasource"] = PROM
    p["targets"] = [pq(expr, legend, instant=True)]
    p["options"]["reduceOptions"] = {"values": False, "calcs": ["lastNotNull"], "fields": ""}
    return p


def ptable(title, columns, by, desc="", overrides=(), labels=None):
    """columns: list of (header, expr, unit). One instant query per column, merged on `by` labels."""
    targets, rename, units = [], {}, []
    for i, (hdr, expr, unit) in enumerate(columns):
        ref = chr(ord("A") + i)
        targets.append(pq(f"max by ({by}) ({expr})", ref=ref, instant=True, fmt="table"))
        rename[f"Value #{ref}"] = hdr
        if unit:
            units.append(unit_override(hdr, unit))
    p = table(title, "SELECT 1", list(units) + list(overrides), desc)
    p["datasource"] = PROM
    p["targets"] = targets
    p["transformations"] = [{"id": "merge", "options": {}},
                            {"id": "organize", "options": {"excludeByName": {"Time": True},
                                                           "renameByName": {**rename, **(labels or {})}}}]
    return p


# re-usable expressions
def host_cpu(sel=HOSTSEL):
    return f'100 * (1 - avg by (nodename) (rate(node_cpu_seconds_total{{mode="idle", {sel}}}[$__rate_interval])))'


def host_mem(sel=HOSTSEL):
    return f'100 * (1 - node_memory_MemAvailable_bytes{{{sel}}} / node_memory_MemTotal_bytes{{{sel}}})'


def host_cores(sel=HOSTSEL):
    return f'count by (nodename) (node_cpu_seconds_total{{mode="idle", {sel}}})'


def running(sel=HOSTSEL):
    return f'(libvirt_domain_info_state{{{sel}}} == 1)'


def vm_rate(metric, sel=VMSEL):
    return f'sum by (nodename, domain) (rate({metric}{{{sel}}}[$__rate_interval]))'


def vm_cpu(sel=VMSEL):
    return (f'100 * {vm_rate("libvirt_domain_info_cpu_time_seconds_total", sel)} '
            f'/ on (nodename, domain) max by (nodename, domain) (libvirt_domain_info_virtual_cpus{{{sel}}})')


def vm_wait(sel=VMSEL):
    return (f'100 * {vm_rate("libvirt_domain_vcpu_delay_seconds_total", sel)} '
            f'/ on (nodename, domain) max by (nodename, domain) (libvirt_domain_info_virtual_cpus{{{sel}}})')


# ------------------------------------------------------------------ filesystems (node_exporter)
FS_STEPS = [{"color": "green", "value": None}, {"color": "#EAB839", "value": 80}, {"color": "red", "value": 90}]
FS_BANDS = [{"color": "transparent", "value": None}, {"color": "#EAB839", "value": 80}, {"color": "red", "value": 90}]
# real filesystems only: drop pseudo/temporary mounts and container layers
FS_FILTER = ('fstype!~"tmpfs|devtmpfs|overlay|squashfs|ramfs|nsfs|tracefs|autofs|efivarfs|iso9660|fuse.*", '
             'mountpoint!~"/run.*|/snap/.*|/var/lib/docker/.*|/var/lib/kubelet/.*"')
FS_GUIDE = """Filesystems on the HVM host itself, from node_exporter (install it with tools/install-exporters.sh).

* **Root (/)** and **/var** hold the OS, logs and libvirt state. A full root filesystem can stop VMs from starting or migrating.
* Local datastores (Directory datastores) live on these filesystems, so they fill up as VM disks grow.
* Shared datastores mounted on the host (NFS, GFS2) appear too, once per host, labelled with their VME datastore name.

Amber at 80%, red at 90%. **Days to full** projects the last 24 hours forward and is blank when usage isn't growing.
**Read-only** usually means the kernel remounted the filesystem after a disk error: investigate straight away."""


def fsname(expr):
    """Add label fs = VME datastore name for datastore mounts, else the mount point.
    vme_datastore_info comes from the collector (mount point -> datastore)."""
    joined = (f"(({expr}) * on (mountpoint) group_left (datastore, datastore_type) vme_datastore_info"
              f" or (({expr}) unless on (mountpoint) vme_datastore_info))")
    return (f'label_replace(label_replace({joined}, "fs", "$1", "mountpoint", "(.*)"),'
            f' "fs", "$1 (datastore)", "datastore", "(.+)")')


def fs_panels(b, sel):
    """Filesystem row for a host selector (label matchers without braces)."""
    fs = f"{sel}, {FS_FILTER}"
    avail, size = f"node_filesystem_avail_bytes{{{fs}}}", f"node_filesystem_size_bytes{{{fs}}}"
    used_pct = f"100 * (1 - {avail} / {size})"
    by = "nodename, fs, fstype, mountpoint"
    full = gauge_cell("Used %", FS_STEPS)
    inode = gauge_cell("Inodes used %", FS_STEPS)
    ro = {"matcher": {"id": "byName", "options": "Read-only"}, "properties": [
        {"id": "mappings", "value": [{"type": "value", "options": {"1": {"text": "READ-ONLY", "color": "red"},
                                                                   "0": {"text": "rw", "color": "green"}}}]},
        {"id": "custom.cellOptions", "value": {"type": "color-text"}}]}
    b.add(ptable("Host filesystems (node_exporter)", [
        ("Size", fsname(size), "bytes"),
        ("Used", fsname(f"{size} - {avail}"), "bytes"),
        ("Available", fsname(avail), "bytes"),
        ("Used %", fsname(used_pct), "percent"),
        ("Inodes used %", fsname(f"100 * (1 - node_filesystem_files_free{{{fs}}} / node_filesystem_files{{{fs}}})"), "percent"),
        ("Days to full", fsname(f"{avail} / (-deriv({avail}[1d]) > 0) / 86400"), "d"),
        ("Read-only", fsname(f"node_filesystem_readonly{{{fs}}}"), None),
    ], by, desc=FS_GUIDE, overrides=[full, inode, ro],
        labels={"nodename": "Host", "fs": "Filesystem", "fstype": "Type", "mountpoint": "Mount point"}), 24, 9)
    b.add(ptime("Filesystem used % (amber 80, red 90)", pq(fsname(used_pct), "{{nodename}} {{fs}}"), "percent",
                minv=0, maxv=100, desc=FS_GUIDE, bands=FS_BANDS), 12, 8)
    b.add(ptime("Filesystem free space", pq(fsname(avail), "{{nodename}} {{fs}}"), "bytes", minv=0, desc=FS_GUIDE), 12, 8)


def hvm_hosts():
    b = Board("vme-hvm-hosts", "VME HVM Hosts & VMs (exporters)", ["exporters", "hosts", "vms"],
              refresh="30s", time_from="now-3h", variables=PROM_VARS)
    b.row("Hosts")
    b.add(ptable("Hosts", [
        ("CPU %", host_cpu(), "percent"),
        ("Memory %", host_mem(), "percent"),
        ("Load / core", f'node_load5{{{HOSTSEL}}} / on (nodename) {host_cores()}', "none"),
        ("Running VMs", f'count by (nodename) {running()} or on (nodename) 0 * node_uname_info{{{HOSTSEL}}}', "none"),
        ("Cores", host_cores(), "none"),
        ("Memory", f'node_memory_MemTotal_bytes{{{HOSTSEL}}}', "bytes"),
        ("Uptime", f'time() - node_boot_time_seconds{{{HOSTSEL}}}', "s"),
    ], "nodename", desc="One row per HVM host, from node_exporter and libvirt exporter."), 24, 7)
    b.add(ptime("Host CPU %", pq(host_cpu(), "{{nodename}}"), "percent", minv=0, maxv=100), 12, 8)
    b.add(ptime("Host memory used %", pq(host_mem(), "{{nodename}}"), "percent", minv=0, maxv=100), 12, 8)
    b.add(ptime("Host disk IOPS", [
        pq(f'sum by (nodename) (rate(node_disk_reads_completed_total{{{HOSTSEL}, {DISK}}}[$__rate_interval]))', "{{nodename}} read"),
        pq(f'sum by (nodename) (rate(node_disk_writes_completed_total{{{HOSTSEL}, {DISK}}}[$__rate_interval]))', "{{nodename}} write", "B")],
        "iops"), 8, 8)
    b.add(ptime("Host disk latency", [
        pq(f'sum by (nodename) (rate(node_disk_read_time_seconds_total{{{HOSTSEL}, {DISK}}}[$__rate_interval])) / sum by (nodename) (rate(node_disk_reads_completed_total{{{HOSTSEL}, {DISK}}}[$__rate_interval]))', "{{nodename}} read"),
        pq(f'sum by (nodename) (rate(node_disk_write_time_seconds_total{{{HOSTSEL}, {DISK}}}[$__rate_interval])) / sum by (nodename) (rate(node_disk_writes_completed_total{{{HOSTSEL}, {DISK}}}[$__rate_interval]))', "{{nodename}} write", "B")],
        "s"), 8, 8)
    b.add(ptime("Host network", [
        pq(f'sum by (nodename) (rate(node_network_receive_bytes_total{{{HOSTSEL}, {NIC}}}[$__rate_interval]))', "{{nodename}} rx"),
        pq(f'-sum by (nodename) (rate(node_network_transmit_bytes_total{{{HOSTSEL}, {NIC}}}[$__rate_interval]))', "{{nodename}} tx", "B")],
        "Bps", desc="Physical interfaces only. Transmit drawn below zero."), 8, 8)
    b.row("Filesystems")
    fs_panels(b, HOSTSEL)
    b.row("Virtual machines")
    b.add(ptable("Virtual machines", [
        ("State", f'libvirt_domain_info_state{{{VMSEL}}}', None),
        ("vCPU", f'libvirt_domain_info_virtual_cpus{{{VMSEL}}}', "none"),
        ("CPU %", vm_cpu(), "percent"),
        ("vCPU wait %", vm_wait(), "percent"),
        ("Memory", f'libvirt_domain_info_maximum_memory_bytes{{{VMSEL}}}', "bytes"),
        ("RSS", f'libvirt_domain_memory_stats_rss_bytes{{{VMSEL}}} * 1', "bytes"),
        ("Read IOPS", vm_rate("libvirt_domain_block_stats_read_requests_total"), "iops"),
        ("Write IOPS", vm_rate("libvirt_domain_block_stats_write_requests_total"), "iops"),
        ("Rx", vm_rate("libvirt_domain_interface_stats_receive_bytes_total"), "Bps"),
        ("Tx", vm_rate("libvirt_domain_interface_stats_transmit_bytes_total"), "Bps"),
    ], "nodename, domain",
        desc="CPU % is of the VM's allocated vCPUs. vCPU wait is the kernel's measure of CPU ready: "
             "healthy under 5%, contention 5 to 10%, VMs slowed above 10%.",
        overrides=[{"matcher": {"id": "byName", "options": "State"}, "properties": [{"id": "mappings", "value": [
            {"type": "value", "options": {"1": {"text": "running", "color": "green"}, "3": {"text": "paused", "color": "orange"},
                                          "5": {"text": "shut off", "color": "gray"}, "6": {"text": "crashed", "color": "red"}}}]},
            {"id": "custom.cellOptions", "value": {"type": "color-text"}}]}]), 24, 10)
    b.add(ptime("Top 10 VMs by CPU %", pq(f"topk(10, {vm_cpu()})", "{{domain}}"), "percent", minv=0), 12, 8)
    b.add(ptime("Top 10 VMs by host memory (RSS)", pq(f"topk(10, libvirt_domain_memory_stats_rss_bytes{{{VMSEL}}})", "{{domain}}"), "bytes", minv=0), 12, 8)
    b.add(ptime("Top 10 VMs by write IOPS", pq(f'topk(10, {vm_rate("libvirt_domain_block_stats_write_requests_total")})', "{{domain}}"), "iops", minv=0), 12, 8)
    b.add(ptime("Top 10 VMs by network receive", pq(f'topk(10, {vm_rate("libvirt_domain_interface_stats_receive_bytes_total")})', "{{domain}}"), "Bps", minv=0), 12, 8)
    return b


def hvm_bottlenecks():
    b = Board("vme-hvm-bottlenecks", "VME HVM Bottlenecks (exporters)", ["exporters", "bottlenecks"],
              refresh="30s", time_from="now-3h", variables=PROM_VARS)
    psi = lambda res, kind: f'100 * rate(node_pressure_{res}_{kind}_seconds_total{{{HOSTSEL}}}[$__rate_interval])'
    b.row("CPU")
    b.add(ptime("CPU pressure (PSI some)", pq(psi("cpu", "waiting"), "{{nodename}}"), "percent", minv=0,
                desc="Share of time at least one task waited for CPU. Sustained values above ~10% mean contention."), 8, 8)
    b.add(ptime("Load per core", pq(f'node_load5{{{HOSTSEL}}} / on (nodename) {host_cores()}', "{{nodename}}"), "none", minv=0,
                desc="5-minute load average divided by cores. Above 1 means queued work."), 8, 8)
    b.add(pbar("Host CPU % now", f"topk(15, {host_cpu()})", "{{nodename}}"), 8, 8)
    wait_guide = READY_GUIDE.replace("**CPU ready**", "**vCPU wait** (the kernel's measure of CPU ready)").replace(
        "VME reports it per VM as the average across its vCPUs, in percent (for a host: across the VMs on it).",
        "Measured by libvirt from the kernel scheduler (vcpu delay), averaged across each VM's vCPUs.").replace(
        "VME added this \"CPU Ready-equivalent metric\" in 9.1.0; HPE doesn't document how it's calculated or a threshold. At low load it reads several times higher than the kernel's\n"
        "own measurement (*vCPU wait* on the exporter dashboards), so these thresholds err on the side of warning early.\n"
        "When the two disagree, trust vCPU wait.", "This is the reference measurement; VME's own CPU ready figure tends to read higher.")
    b.add(ptime("Top 10 VMs by vCPU wait % (healthy < 5%, act > 10%)", pq(f"topk(10, {vm_wait()})", "{{domain}}"), "percent",
                minv=0, desc=wait_guide, bands=READY_STEPS), 16, 8)
    b.add(pbar("vCPU wait % now (healthy < 5%)", f"topk(15, {vm_wait()})", "{{domain}}", maxv=20,
               steps=READY_TILE_STEPS, desc=wait_guide), 8, 8)
    b.row("Memory")
    b.add(ptime("Memory pressure (PSI)", [pq(psi("memory", "waiting"), "{{nodename}} some"),
                                         pq(psi("memory", "stalled"), "{{nodename}} full", "B")], "percent", minv=0), 8, 8)
    b.add(ptime("Host memory used %", pq(host_mem(), "{{nodename}}"), "percent", minv=0, maxv=100), 8, 8)
    b.add(ptime("Host swap used", pq(f'node_memory_SwapTotal_bytes{{{HOSTSEL}}} - node_memory_SwapFree_bytes{{{HOSTSEL}}}', "{{nodename}}"), "bytes", minv=0), 8, 8)
    b.add(ptime("Top 10 VMs by swap in", pq(f'topk(10, {vm_rate("libvirt_domain_memory_stats_swap_in_bytes")})', "{{domain}}"), "Bps", minv=0,
                desc="Needs the virtio balloon driver in the guest."), 12, 8)
    b.add(ptime("Top 10 VMs by major page faults", pq(f'topk(10, {vm_rate("libvirt_domain_memory_stats_major_fault_total")})', "{{domain}}"), "ops", minv=0), 12, 8)
    b.row("Disk")
    b.add(ptime("I/O pressure (PSI)", [pq(psi("io", "waiting"), "{{nodename}} some"),
                                       pq(psi("io", "stalled"), "{{nodename}} full", "B")], "percent", minv=0), 8, 8)
    b.add(ptime("Host disk busy %", pq(f'100 * max by (nodename) (rate(node_disk_io_time_seconds_total{{{HOSTSEL}, {DISK}}}[$__rate_interval]))', "{{nodename}}"), "percent", minv=0, maxv=100), 8, 8)
    b.add(ptime("Host disk write latency", pq(
        f'sum by (nodename) (rate(node_disk_write_time_seconds_total{{{HOSTSEL}, {DISK}}}[$__rate_interval])) / sum by (nodename) (rate(node_disk_writes_completed_total{{{HOSTSEL}, {DISK}}}[$__rate_interval]))',
        "{{nodename}}"), "s", minv=0), 8, 8)
    b.add(ptime("Top 10 VMs by write latency", pq(
        f'topk(10, {vm_rate("libvirt_domain_block_stats_write_time_seconds_total")} / {vm_rate("libvirt_domain_block_stats_write_requests_total")})',
        "{{domain}}"), "s", minv=0), 12, 8)
    b.add(ptime("Top 10 VMs by IOPS (noisy neighbours)", pq(
        f'topk(10, {vm_rate("libvirt_domain_block_stats_read_requests_total")} + {vm_rate("libvirt_domain_block_stats_write_requests_total")})',
        "{{domain}} on {{nodename}}"), "iops", minv=0), 12, 8)
    b.row("Network")
    drop = lambda kind: (f'sum by (nodename, device) (rate(node_network_receive_{kind}_total{{{HOSTSEL}, {NIC}}}[$__rate_interval]) '
                         f'+ rate(node_network_transmit_{kind}_total{{{HOSTSEL}, {NIC}}}[$__rate_interval]))')
    b.add(ptime("Host interface drops", pq(drop("drop"), "{{nodename}} {{device}}"), "pps", minv=0), 8, 8)
    b.add(ptime("Host interface errors", pq(drop("errs"), "{{nodename}} {{device}}"), "pps", minv=0), 8, 8)
    b.add(ptime("Top 10 VMs by dropped packets", pq(
        f'topk(10, {vm_rate("libvirt_domain_interface_stats_receive_drops_total")} + {vm_rate("libvirt_domain_interface_stats_transmit_drops_total")})',
        "{{domain}}"), "pps", minv=0), 8, 8)
    return b


def hvm_capacity():
    b = Board("vme-hvm-capacity", "VME HVM Capacity (exporters)", ["exporters", "capacity"],
              refresh="5m", time_from="now-30d", variables=PROM_VARS[:3])
    vcpus = f'sum by (nodename) (libvirt_domain_info_virtual_cpus{{{HOSTSEL}}} and on (nodename, domain) {running()})'
    vmem = f'sum by (nodename) (libvirt_domain_info_maximum_memory_bytes{{{HOSTSEL}}} and on (nodename, domain) {running()})'
    b.row("Allocation")
    b.add(ptable("Capacity per host", [
        ("Cores", host_cores(), "none"),
        ("vCPUs (running VMs)", vcpus, "none"),
        ("vCPU : core", f"{vcpus} / {host_cores()}", "none"),
        ("Idle cores", f'{host_cores()} * avg by (nodename) (rate(node_cpu_seconds_total{{mode="idle", {HOSTSEL}}}[$__rate_interval]))', "none"),
        ("Memory", f'node_memory_MemTotal_bytes{{{HOSTSEL}}}', "bytes"),
        ("Allocated to VMs", vmem, "bytes"),
        ("Allocated / host", f'{vmem} / on (nodename) node_memory_MemTotal_bytes{{{HOSTSEL}}}', "percentunit"),
        ("Available", f'node_memory_MemAvailable_bytes{{{HOSTSEL}}}', "bytes"),
    ], "nodename"), 24, 7)
    b.add(pbar("vCPU : core ratio", f"topk(15, {vcpus} / {host_cores()})", "{{nodename}}", unit="none", maxv=None,
               steps=[{"color": "green", "value": None}, {"color": "#EAB839", "value": 4}, {"color": "red", "value": 8}]), 12, 8)
    b.add(pbar("Memory allocated / host memory", f"topk(15, 100 * {vmem} / on (nodename) node_memory_MemTotal_bytes{{{HOSTSEL}}})", "{{nodename}}",
               maxv=150, steps=[{"color": "green", "value": None}, {"color": "#EAB839", "value": 80}, {"color": "red", "value": 100}],
               desc="Above 100% means memory is overcommitted."), 12, 8)
    fsel = f"{HOSTSEL}, {FS_FILTER}"
    b.add(pbar("Filesystems: days until full (lowest 15)",
               f'bottomk(15, node_filesystem_avail_bytes{{{fsel}}} / (-deriv(node_filesystem_avail_bytes{{{fsel}}}[1d]) > 0) / 86400)',
               "{{nodename}} {{mountpoint}}", unit="d", maxv=90,  # mount point: short enough for a bar label
               steps=[{"color": "red", "value": None}, {"color": "#EAB839", "value": 14}, {"color": "green", "value": 30}],
               desc="At the growth rate of the last 24 hours. Only filesystems that are growing are listed."), 24, 7)
    b.row("Trends")
    b.add(ptime("Host CPU %", pq(host_cpu(), "{{nodename}}"), "percent", minv=0, maxv=100), 8, 8)
    b.add(ptime("Host memory used %", pq(host_mem(), "{{nodename}}"), "percent", minv=0, maxv=100), 8, 8)
    b.add(ptime("Running VMs", pq(f'count by (nodename) {running()}', "{{nodename}}"), "none", minv=0, stack=True), 8, 8)
    return b


# ------------------------------------------------------------------ data export
EXPORT_HOWTO = """**Exporting a panel as CSV:** hover the panel, open its menu (⋮) and choose **Inspect → Data**, then **Download CSV**.

* Pick what to export with the variables above and the **time range** at the top right. Every panel follows them.
* **Formatted data** on: values with units (e.g. `12.3 GiB`). Off: raw numbers, best for spreadsheets and scripts.
* **Download for Excel**: adds the byte-order mark Excel needs for non-ASCII names.
* For the *one column per entity* panel, choose **Series joined by time** in Inspect → Data options.
* Tables are capped at 200,000 rows. For bigger pulls use `tools/export_csv.py` on the vme-insight host (see docs/EXPORTS.md)."""

KIND_VAR = {"type": "custom", "name": "kind", "label": "Kind", "query": "host,vm,cluster,datastore,appliance,summary",
            "current": {"text": "host", "value": "host"}, "multi": False, "includeAll": False,
            "options": [{"text": k, "value": k, "selected": k == "host"}
                        for k in ("host", "vm", "cluster", "datastore", "appliance", "summary")]}
ENTITY_VAR = qvar("entity", "Entity", """SELECT name AS __text, entity_id AS __value FROM entity_names
    WHERE entity_type = '$kind' ORDER BY present DESC, name""")
METRIC_VAR = {"type": "query", "name": "metric", "label": "Metric", "datasource": DS,
              "query": "SELECT DISTINCT metric FROM metrics WHERE entity_type = '$kind' AND time > now() - INTERVAL '2 days' ORDER BY 1",
              "definition": "metrics seen for this kind in the last 2 days", "refresh": 2, "multi": True,
              "includeAll": True, "allValue": "'__all__'", "sort": 1,
              "current": {"selected": True, "text": ["cpu_pct"], "value": ["cpu_pct"]}}
RES_VAR = {"type": "custom", "name": "res", "label": "Resolution",
           "query": "1 minute,5 minutes,15 minutes,1 hour,1 day",
           "current": {"text": "5 minutes", "value": "5 minutes"}, "multi": False, "includeAll": False,
           "options": [{"text": v, "value": v, "selected": v == "5 minutes"}
                       for v in ("1 minute", "5 minutes", "15 minutes", "1 hour", "1 day")]}

EF = "(-1 IN ($entity) OR m.entity_id IN ($entity))"
MF = "('__all__' IN ($metric) OR m.metric IN ($metric))"
CSV_NOTE = "\n\nExport: panel menu → Inspect → Data → Download CSV."


def export_board():
    b = Board("vme-export", "VME Data Export", ["export", "csv"], refresh="", time_from="now-24h",
              variables=[KIND_VAR, ENTITY_VAR, METRIC_VAR, RES_VAR])
    b.add({"type": "text", "title": "How to export", "options": {"mode": "markdown", "content": EXPORT_HOWTO}}, 24, 6)

    b.row("Time series")
    b.add(table("Metric samples (long format: one row per time, entity, metric)", f"""
        SELECT time_bucket(INTERVAL '$res', m.time) AS "time", m.entity_type AS "kind", e.name AS "entity",
               m.entity_id AS "entity_id", m.metric AS "metric",
               avg(m.value) AS "avg", min(m.value) AS "min", max(m.value) AS "max", count(*) AS "samples"
        FROM metrics m LEFT JOIN entity_names e ON e.entity_type = m.entity_type AND e.entity_id = m.entity_id
        WHERE $__timeFilter(m.time) AND m.entity_type = '$kind' AND {EF} AND {MF}
        GROUP BY 1, 2, 3, 4, 5 ORDER BY 1, 3, 5 LIMIT 200000""",
        desc="Raw samples averaged into the chosen resolution, with min, max and sample count per bucket. "
             "Raw data is kept for retention.raw days (default 90); use the hourly rollup panel for older data." + CSV_NOTE), 24, 10)
    b.add(timeseries("One column per entity (first selected metric)", f"""
        SELECT time_bucket(INTERVAL '$res', m.time) AS "time", e.name || ' ' || m.metric AS metric, avg(m.value) AS value
        FROM metrics m LEFT JOIN entity_names e ON e.entity_type = m.entity_type AND e.entity_id = m.entity_id
        WHERE $__timeFilter(m.time) AND m.entity_type = '$kind' AND {EF} AND {MF}
        GROUP BY 1, 2 ORDER BY 1""", "none", legend="table",
        desc="Wide layout for spreadsheets: in Inspect → Data options choose **Series joined by time** to get one "
             "column per entity and metric." + CSV_NOTE), 24, 8)
    b.add(table("Hourly rollups (long-term: avg, min, max per hour)", f"""
        SELECT h.bucket AS "hour", h.entity_type AS "kind", e.name AS "entity", h.entity_id AS "entity_id",
               h.metric AS "metric", h.avg AS "avg", h.min AS "min", h.max AS "max", h.samples AS "samples"
        FROM metrics_hourly h LEFT JOIN entity_names e ON e.entity_type = h.entity_type AND e.entity_id = h.entity_id
        WHERE $__timeFilter(h.bucket) AND h.entity_type = '$kind'
          AND (-1 IN ($entity) OR h.entity_id IN ($entity)) AND ('__all__' IN ($metric) OR h.metric IN ($metric))
        ORDER BY 1, 3, 5 LIMIT 200000""",
        desc="From the hourly continuous aggregate, kept for retention.hourly days (default 730). Use it for "
             "trends longer than the raw retention. The newest hour or two appear once the rollup refreshes." + CSV_NOTE), 24, 8)

    b.row("Inventory (current)")
    b.add(table("Hosts and VMs (full inventory with lifecycle status)", """
        SELECT s.id, s.kind, s.name, s.hostname, sc.cloud, sc.cluster, sc.host, s.power_state, s.status,
               s.ip_internal, s.ip_external, s.max_cores AS vcpu_or_cores, s.max_memory AS memory_bytes,
               s.max_storage AS storage_bytes, s.os_name, s.platform, s.platform_version, s.os_product, s.os_cycle,
               sc.os_status, sc.eol_date, sc.days_to_eol, sc.os_latest, s.agent_installed, s.agent_version,
               sc.agent_status, s.agent_last_update, s.guest_agent_status, s.maintenance, s.member_status,
               s.cpu_model, s.hw_vendor, s.hw_model, s.plan, s.source_image, s.type_code, s.date_created,
               s.first_seen, s.last_seen
        FROM servers s LEFT JOIN server_currency sc ON sc.id = s.id WHERE s.present ORDER BY s.kind, s.name""",
        desc="Every current host and VM with its OS, agent and lifecycle status." + CSV_NOTE), 24, 8)
    b.add(table("Datastores", """
        SELECT d.id, d.name, d.type, d.status, cl.name AS cluster, cd.name AS cloud, d.capacity_bytes, d.free_bytes,
               d.capacity_bytes - d.free_bytes AS used_bytes,
               round(100.0 * (d.capacity_bytes - d.free_bytes) / NULLIF(d.capacity_bytes, 0), 2) AS used_pct,
               d.raw->>'externalPath' AS host_mount_path, d.first_seen, d.last_seen
        FROM datastores d LEFT JOIN clusters cl ON cl.id = d.cluster_id LEFT JOIN clouds cd ON cd.id = d.cloud_id
        WHERE d.present ORDER BY d.name""", desc="Current datastores." + CSV_NOTE), 12, 7)
    b.add(table("Clusters, instances and networks", """
        SELECT 'cluster' AS object, id, name, type_name AS type, status, layout AS detail, NULL::text AS owner FROM clusters WHERE present
        UNION ALL SELECT 'instance', id, name, instance_type, status, plan, owner FROM instances WHERE present
        UNION ALL SELECT 'network', id, name, type, status, cidr, NULL FROM networks WHERE present
        ORDER BY 1, 3""", desc="Other current inventory objects." + CSV_NOTE), 12, 7)

    b.row("Events in the time range")
    b.add(table("Inventory changes", """
        SELECT time, entity_type AS kind, entity_id, name, field, old_value, new_value
        FROM inventory_changes WHERE $__timeFilter(time) ORDER BY time LIMIT 200000""",
        desc="Every change to hosts and VMs: discovery, removal, power, OS, agent, size, host (migration) and more." + CSV_NOTE), 24, 7)
    b.add(table("Alarms", """
        SELECT start_date, last_seen, severity, name, resource_name, ref_type, ref_id, message, acknowledged, active
        FROM alarms WHERE start_date <= $__timeTo() AND last_seen >= $__timeFrom() ORDER BY start_date""",
        desc="Alarms that were open at any point in the time range." + CSV_NOTE), 12, 7)
    b.add(table("Activity", """
        SELECT ts, activity_type, object_type, name, message, user_name, success
        FROM activity WHERE $__timeFilter(ts) ORDER BY ts""",
        desc="VME's activity feed (provisioning, alerts, backups) as collected." + CSV_NOTE), 12, 7)

    b.row("One object, everything VME returns")
    b.add(table("Raw API record of one object (secrets redacted)", """
        WITH r AS (SELECT raw FROM (
          SELECT name, raw FROM servers WHERE kind = '$kind' AND (-1 IN ($entity) OR id IN ($entity))
          UNION ALL SELECT name, raw FROM clusters WHERE '$kind' = 'cluster' AND (-1 IN ($entity) OR id IN ($entity))
          UNION ALL SELECT name, raw FROM datastores WHERE '$kind' = 'datastore' AND (-1 IN ($entity) OR id IN ($entity))
          UNION ALL SELECT 'VME manager', health FROM appliance WHERE '$kind' = 'appliance') x ORDER BY name LIMIT 1)
        SELECT f.key AS field, f.value AS value
        FROM r, jsonb_each_text(r.raw) f ORDER BY 1""",
        desc="Every field VME's API returned for the object, as stored by the collector. With several entities "
             "(or All) selected, the first by name is shown. For the manager this is the /api/health document. Useful when a value on a dashboard "
             "looks wrong or to find fields that have no column yet." + CSV_NOTE), 24, 10)
    return b


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for fn, name in ((overview, "vme-overview"), (hosts, "vme-hosts"), (vms, "vme-vms"),
                     (lifecycle_board, "vme-lifecycle"), (health, "vme-health"),
                     (hvm_hosts, "vme-hvm-hosts"), (hvm_bottlenecks, "vme-hvm-bottlenecks"),
                     (hvm_capacity, "vme-hvm-capacity"), (export_board, "vme-export"),
                     (widget_board, "vme-widget")):
        (OUT / f"{name}.json").write_text(json.dumps(fn().json(), indent=2) + "\n")
        print(f"wrote {name}.json")


if __name__ == "__main__":
    main()
