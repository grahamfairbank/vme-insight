"""Collection tasks. Each task returns the number of items it handled."""
import json
import logging
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from psycopg.types.json import Jsonb

from . import osdetect
from .morpheus import ApiError

log = logging.getLogger(__name__)
MIN_VERSION = (9, 1)  # oldest VME release this project is tested against

# Canonical metric name -> candidate fields, searched in server.stats, then the
# server itself, then server.capacityInfo. Every numeric field of stats is also
# stored as "raw.<field>" so nothing is lost if the API adds fields.
CANONICAL = {
    "cpu_pct": ["cpuUsage", "usedCpu"],
    "mem_used_bytes": ["usedMemory"],
    "mem_total_bytes": ["maxMemory"],
    "mem_reserved_bytes": ["reservedMemory"],
    "storage_used_bytes": ["usedStorage"],
    "storage_total_bytes": ["maxStorage"],
    "net_rx": ["netRxUsage"],
    "net_tx": ["netTxUsage"],
    "disk_iops": ["totalIOPS", "iops", "totalIops"],
    "swap_used_bytes": ["usedSwap"],
    "swap_free_bytes": ["freeSwap"],
    "mem_free_bytes": ["freeMemory"],
    "cpu_ready_pct": ["cpuReady"],
    "storage_reserved_bytes": ["reservedStorage"],
    "disk_read_iops": ["readIOPS", "readIops"],
    "disk_write_iops": ["writeIOPS", "writeIops"],
    "cores": ["maxCores"],
}

CANONICAL_FIELDS = {f for fields in CANONICAL.values() for f in fields}


# Fields never stored: agent API keys, credentials, passwords and their hashes, tokens.
SECRET_KEY = re.compile(r"(?i)(password|passwd|secret|token|apikey|api_key|credential|privatekey|private_key|hash$|^key$)")


def scrub(o):
    if isinstance(o, dict):
        return {k: ("<redacted>" if SECRET_KEY.search(k) and v not in (None, "", [], {}) else scrub(v))
                for k, v in o.items()}
    if isinstance(o, list):
        return [scrub(v) for v in o]
    return o


def J(obj):
    """JSON for a raw column, with secrets removed."""
    return Jsonb(scrub(obj))


def now():
    return datetime.now(timezone.utc)


def num(v):
    if isinstance(v, bool) or v is None:
        return None
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if f == f else None  # drop NaN


def ref_id(v):
    if isinstance(v, dict):
        v = v.get("id")
    try:
        return int(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def ids_from(*values):
    out = set()
    for v in values:
        for item in v or []:
            i = ref_id(item)
            if i is not None:
                out.add(i)
    return out


def ts(v):
    if not v or not isinstance(v, str):
        return None
    try:
        return datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None


def flatten_numeric(d, prefix="", depth=3):
    out = {}
    if not isinstance(d, dict) or depth < 0:
        return out
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(flatten_numeric(v, key + ".", depth - 1))
        else:
            n = num(v)
            if n is not None:
                out[key] = n
    return out


def pct(used, total):
    if used is None or not total:
        return None
    return 100.0 * used / total


HEALTHY = ("ok", "green", "yellow", "up", "online", "healthy")


def health_points(h):
    """Curated numeric view of /api/health (the raw document is kept in appliance.health)."""
    out = {}
    for sect in ("cpu", "memory"):
        for k, v in (h.get(sect) or {}).items():
            if num(v) is not None:
                # VME reports memory.*Percent as fractions (0.73 = 73%); store real percentages
                scale = 100.0 if sect == "memory" and k.endswith("Percent") else 1.0
                out[f"{sect}.{k}"] = num(v) * scale
    st = h.get("storage") or {}
    for k in ("total", "used", "available", "percent"):
        if num(st.get(k)) is not None:
            out[f"storage.{k}"] = num(st[k])
    for f in st.get("files") or []:
        name = f.get("path") or f.get("name")
        for k in ("percent", "used", "available", "total"):
            if name and num(f.get(k)) is not None:
                out[f"storage.fs.{name}.{k}"] = num(f[k])
    db = h.get("database") or {}
    for k in ("maxConnections", "usedConnections", "maxUsedConnections", "abortedConnections"):
        if num(db.get(k)) is not None:
            out[f"database.{k}"] = num(db[k])
    out["database.busyConnections"] = float(len(db.get("busyConnections") or []))
    es = h.get("elastic") or {}
    for n in es.get("nodes") or []:
        for k in ("heapPercent", "ramPercent", "loadOne", "loadFive"):
            if num(n.get(k)) is not None:
                out[f"elastic.{n.get('name', 'node')}.{k}"] = num(n[k])
    rb = h.get("rabbit") or {}
    queues = rb.get("queues") or []
    out["rabbit.queued_messages"] = float(sum(num(q.get("count")) or 0 for q in queues))
    out["rabbit.busy_queues"] = float(len(rb.get("busyQueues") or []))
    out["rabbit.error_queues"] = float(len(rb.get("errorQueues") or []))
    for q in queues:
        if (num(q.get("count")) or 0) > 0:
            out[f"rabbit.queue.{q.get('name')}"] = num(q["count"])
    out["threads.busy"] = float(len((h.get("threads") or {}).get("busyThreads") or []))
    for svc in ("cpu", "memory", "storage", "database", "elastic", "rabbit"):
        status = (h.get(svc) or {}).get("status")
        if isinstance(status, str):
            out[f"service.{svc}.ok"] = 1.0 if status.lower() in HEALTHY else 0.0
    return out


class Collector:
    def __init__(self, api, db, cfg):
        self.api = api
        self.db = db
        self.cfg = cfg
        cls = cfg["classification"]
        self.host_codes = {c.lower() for c in cls.get("host_type_codes") or []}
        self.vm_codes = {c.lower() for c in cls.get("vm_type_codes") or []}
        self.os_rules = cfg["lifecycle"].get("os_rules") or []
        self.cluster_of_host = {}

    # ------------------------------------------------------------ helpers
    def classify(self, srv):
        cst = srv.get("computeServerType") or {}
        code = (cst.get("code") or "").lower()
        if code in self.vm_codes:
            return "vm"
        if code in self.host_codes or cst.get("vmHypervisor") or cst.get("containerHypervisor"):
            return "host"
        # HVM hosts are "mvmHost" with nodeType "morpheus-node" (VME 9.1)
        if code.endswith("host") or "hypervisor" in code or cst.get("nodeType") == "morpheus-node":
            return "host"
        return "vm"

    def _try_list(self, path, key, params=None):
        try:
            return self.api.list(path, key, params)[0]
        except ApiError as e:
            if e.status in (403, 404):
                log.debug("skip %s: %s", path, e)
                return None
            raise

    # ------------------------------------------------------------ metrics: servers + clusters
    def metrics(self):
        t = now()
        clusters, _ = self.api.list("/api/clusters", "clusters")
        cluster_of_host = {}
        crows = []
        for c in clusters:
            hosts = ids_from(c.get("servers"), c.get("workers"), c.get("hosts"), c.get("managers"))
            for h in hosts:
                cluster_of_host[h] = c["id"]
            ctype = c.get("type") or {}
            crows.append(dict(
                id=c["id"], name=c.get("name"), type_code=ctype.get("code"), type_name=ctype.get("name"),
                cloud_id=ref_id(c.get("zone") or c.get("cloud")), status=c.get("status"),
                layout=(c.get("layout") or {}).get("name"), host_ids=sorted(hosts), raw=J(c)))
        self.db.mark_absent("clusters", [c["id"] for c in clusters])

        # clusters that don't list their members: ask the API which servers belong to them
        for c in clusters:
            if c["id"] in cluster_of_host.values():
                continue
            members = self._try_list("/api/servers", "servers", {"clusterId": c["id"]}) or []
            for m in members:
                cluster_of_host.setdefault(m["id"], c["id"])
                crows_by_id = next(r for r in crows if r["id"] == c["id"])
                crows_by_id["host_ids"] = sorted(set(crows_by_id["host_ids"]) | {m["id"]})
        self.db.upsert("clusters", crows)

        servers, extras = self.api.list("/api/servers", "servers")
        side = extras.get("stats") or {}
        for s in servers:  # the side map carries reserved memory/storage; server.stats wins on overlap
            extra = side.get(str(s["id"])) or {}
            s["stats"] = {**{k: v for k, v in extra.items() if v is not None}, **(s.get("stats") or {})}
        # servers may also name their cluster directly
        for s in servers:
            cid = ref_id(s.get("cluster") or s.get("serverGroup"))
            if cid and self.classify(s) == "host":
                cluster_of_host.setdefault(s["id"], cid)
        kinds = {s["id"]: self.classify(s) for s in servers}
        cluster_of_host = {h: c for h, c in cluster_of_host.items() if kinds.get(h, "host") == "host"}
        self.cluster_of_host = cluster_of_host

        rows, points = [], []
        kind_of = {}
        for s in servers:
            kind = self.classify(s)
            kind_of[s["id"]] = kind
            rows.append(self._server_row(s, kind))
            points.extend(self._server_points(s, kind))
        self.db.upsert("servers", rows)
        self.db.mark_absent("servers", [s["id"] for s in servers])
        self._write_targets([r for r in rows if r["kind"] == "host"], {c["id"]: c.get("name") for c in clusters})

        # roll-ups: per host, per cluster, fleet summary
        latest = defaultdict(dict)  # (kind,id) -> metric -> value
        for et, eid, m, v in points:
            latest[(et, eid)][m] = v
        vms_on_host = defaultdict(lambda: [0, 0])
        summary = defaultdict(float)
        for r in rows:
            k = r["kind"]
            summary[f"{k}s_total"] += 1
            state = (r["power_state"] or "unknown").lower()
            summary[f"{k}s_{state}"] += 1
            if k == "vm" and r["host_id"]:
                vms_on_host[r["host_id"]][0] += 1
                vms_on_host[r["host_id"]][1] += state == "on"
        for hid, (total, running) in vms_on_host.items():
            if kind_of.get(hid) == "host":
                points.append(("host", hid, "vm_count", total))
                points.append(("host", hid, "vm_running", running))

        agg = defaultdict(lambda: defaultdict(list))
        for (et, eid), mets in latest.items():
            if et != "host" or eid not in cluster_of_host:
                continue
            a = agg[cluster_of_host[eid]]
            for m in ("cpu_pct", "mem_used_bytes", "mem_total_bytes", "storage_used_bytes",
                      "storage_total_bytes", "net_rx", "net_tx", "cores"):
                if m in mets:
                    a[m].append(mets[m])
            a["vm_count"].append(vms_on_host.get(eid, [0, 0])[0])
            a["vm_running"].append(vms_on_host.get(eid, [0, 0])[1])
        for cid, a in agg.items():
            if a["cpu_pct"]:
                points.append(("cluster", cid, "cpu_pct", sum(a["cpu_pct"]) / len(a["cpu_pct"])))
            for m in ("mem_used_bytes", "mem_total_bytes", "storage_used_bytes", "storage_total_bytes",
                      "net_rx", "net_tx", "cores", "vm_count", "vm_running"):
                if a[m]:
                    points.append(("cluster", cid, m, sum(a[m])))
            points.append(("cluster", cid, "host_count", len(a["vm_count"])))
            mp = pct(sum(a["mem_used_bytes"]), sum(a["mem_total_bytes"]))
            sp = pct(sum(a["storage_used_bytes"]), sum(a["storage_total_bytes"]))
            if mp is not None:
                points.append(("cluster", cid, "mem_pct", mp))
            if sp is not None:
                points.append(("cluster", cid, "storage_pct", sp))
        for c in clusters:  # whatever stats the cluster object itself carries
            for k, v in flatten_numeric(c.get("stats"), "raw.").items():
                points.append(("cluster", c["id"], k, v))
            for k, v in flatten_numeric(c.get("workerStats"), "raw.worker.").items():
                points.append(("cluster", c["id"], k, v))

        for m, v in summary.items():
            points.append(("summary", 0, m, v))
        points.append(("summary", 0, "clusters_total", len(clusters)))
        return self.db.write_metrics(t, points)

    def _write_targets(self, hosts, cluster_names):
        ex = self.cfg.get("exporters") or {}
        if not ex.get("enabled", True):
            return
        field = {"internal": "ip_internal", "external": "ip_external", "hostname": "hostname"}[ex.get("address", "internal")]
        outdir = Path(ex.get("targets_dir", "/targets"))
        if not outdir.is_dir():
            return
        for job, port in (("node", ex.get("node_port", 9100)), ("libvirt", ex.get("libvirt_port", 9177))):
            groups = []
            for h in sorted(hosts, key=lambda r: r["name"] or ""):
                addr = h.get(field) or h.get("ip_internal") or h.get("hostname")
                if not addr:
                    continue
                groups.append({"targets": [f"{addr}:{port}"], "labels": {
                    "nodename": h["name"] or addr, "cluster": cluster_names.get(h["cluster_id"]) or "",
                    "vme_host_id": str(h["id"]), "source": ex.get("source", "vme")}})
            tmp = outdir / f".hvm-{job}.json.tmp"
            tmp.write_text(json.dumps(groups, indent=1))
            tmp.replace(outdir / f"hvm-{job}.json")  # atomic, Prometheus never sees a partial file
        # the VME manager itself, for node_exporter inside the manager VM
        mgr = ex.get("manager_address") or urlsplit(self.api.base).hostname
        if mgr:
            tmp = outdir / ".vme-manager.json.tmp"
            tmp.write_text(json.dumps([{"targets": [f"{mgr}:{ex.get('node_port', 9100)}"], "labels": {
                "nodename": "vme-manager", "role": "manager", "source": ex.get("source", "vme")}}], indent=1))
            tmp.replace(outdir / "vme-manager.json")

    def _server_row(self, s, kind):
        cst = s.get("computeServerType") or {}
        os_ = s.get("serverOs") or {}
        product, cycle, full = osdetect.detect(s, self.os_rules)
        host_id = ref_id(s.get("parentServer")) if kind == "vm" else None
        cluster_id = self.cluster_of_host.get(host_id if kind == "vm" else s["id"])
        return dict(
            id=s["id"], kind=kind, name=s.get("name"), hostname=s.get("hostname"),
            cloud_id=ref_id(s.get("zone") or s.get("cloud")), cluster_id=cluster_id, host_id=host_id,
            type_code=cst.get("code"), type_name=cst.get("name"), managed=cst.get("managed"),
            status=s.get("status"), power_state=s.get("powerState"),
            ip_internal=s.get("internalIp"), ip_external=s.get("externalIp"),
            os_name=os_.get("name"), os_type=s.get("osType"),
            platform=s.get("platform"), platform_version=s.get("platformVersion"),
            os_product=product, os_cycle=cycle, os_version_full=full,
            agent_installed=bool(s.get("agentInstalled")), agent_version=s.get("agentVersion"),
            agent_last_update=ts(s.get("lastAgentUpdate")),
            max_cores=s.get("maxCores"), max_memory=s.get("maxMemory"), max_storage=s.get("maxStorage"),
            date_created=ts(s.get("dateCreated")),
            guest_agent_status=s.get("guestAgentStatus"), maintenance=s.get("maintenanceMode"),
            member_status=s.get("serverGroupMemberStatus"),
            hw_vendor=(s.get("hardwareProductVendor") or "").strip() or None,
            hw_model=(s.get("hardwareProductName") or "").strip() or None,
            cpu_model=s.get("hardwareCpuModel"), cpu_sockets=s.get("maxSockets"),
            plan=(s.get("plan") or {}).get("name"), source_image=(s.get("sourceImage") or {}).get("name"),
            raw=J(s),
        )

    def _server_points(self, s, kind):
        stats = s.get("stats") or {}
        sources = (stats, s, s.get("capacityInfo") or {})
        vals = {}
        for name, fields in CANONICAL.items():
            for src in sources:
                v = next((num(src.get(f)) for f in fields if num(src.get(f)) is not None), None)
                if v is not None:
                    vals[name] = v
                    break
        mp = pct(vals.get("mem_used_bytes"), vals.get("mem_total_bytes"))
        sp = pct(vals.get("storage_used_bytes"), vals.get("storage_total_bytes"))
        if mp is not None:
            vals["mem_pct"] = mp
        if sp is not None:
            vals["storage_pct"] = sp
        if (s.get("powerState") or "").lower() != "on":
            # stopped servers report stale stats; keep capacity only
            vals = {k: v for k, v in vals.items() if k.endswith("total_bytes") or k == "cores"}
        per_vcpu = [num(v) for k, v in stats.items() if k.startswith("cpuReadyVcpu") and num(v) is not None]
        if per_vcpu and "cpu_ready_pct" in vals:
            vals["cpu_ready_max_vcpu_pct"] = max(per_vcpu)  # one starved vCPU hides in the average
        vals["up"] = 1.0 if (s.get("powerState") or "").lower() == "on" else 0.0
        if s.get("guestAgentStatus") and kind == "vm":
            vals["guest_agent_connected"] = 1.0 if s["guestAgentStatus"] == "connected" else 0.0
        for k, v in flatten_numeric(stats, "", depth=1).items():
            if k != "ts" and k not in CANONICAL_FIELDS:  # don't store the same value twice
                vals["raw." + k] = v
        return [(kind, s["id"], m, v) for m, v in vals.items()]

    # ------------------------------------------------------------ storage
    def storage(self):
        t = now()
        found = {d["id"]: d for d in self._try_list("/api/data-stores", "datastores") or []}
        if not found:  # older APIs: per-cluster and per-cloud datastore lists
            for (cid,) in self.db.execute("SELECT id FROM clusters WHERE present") or []:
                for d in self._try_list(f"/api/clusters/{cid}/datastores", "datastores") or []:
                    found.setdefault(d["id"], dict(d, _cluster_id=cid))
            for (zid,) in self.db.execute("SELECT id FROM clouds WHERE present") or []:
                for d in self._try_list(f"/api/zones/{zid}/data-stores", "datastores") or []:
                    found.setdefault(d["id"], dict(d, _cloud_id=zid))
        rows, points = [], []
        for d in found.values():
            cap = num(d.get("storageSize") or d.get("maxStorage") or d.get("capacity"))
            free = num(d.get("freeSpace") if d.get("freeSpace") is not None else d.get("freeStorage"))
            rows.append(dict(
                id=d["id"], name=d.get("name"),
                type=(d.get("datastoreType") or {}).get("name") or (
                    d["type"].get("name") if isinstance(d.get("type"), dict) else d.get("type")),
                cloud_id=ref_id(d.get("zone")) or d.get("_cloud_id"), cluster_id=d.get("_cluster_id"),
                active=d.get("active"),
                status=d.get("status") or ({True: "online", False: "offline"}.get(d.get("online"))),
                capacity_bytes=int(cap) if cap is not None else None,
                free_bytes=int(free) if free is not None else None,
                raw=J({k: v for k, v in d.items() if not k.startswith("_")})))
            if cap:
                points.append(("datastore", d["id"], "capacity_bytes", cap))
                if free is not None:
                    points.append(("datastore", d["id"], "free_bytes", free))
                    points.append(("datastore", d["id"], "used_bytes", cap - free))
                    points.append(("datastore", d["id"], "used_pct", pct(cap - free, cap)))
            if d.get("online") is not None:
                points.append(("datastore", d["id"], "online", 1.0 if d.get("online") else 0.0))
        self.db.upsert("datastores", rows)
        if found:
            self.db.mark_absent("datastores", found.keys())
        self.db.write_metrics(t, points)
        return len(rows)

    # ------------------------------------------------------------ health + alarms
    def health(self):
        t = now()
        points = []
        try:
            h = self.api.get("/api/health")
            health = h.get("health") or h
            points.extend(("appliance", 0, k, v) for k, v in health_points(health).items())
            self.db.execute("UPDATE appliance SET health = %s, health_at = now() WHERE id = 1", (J(health),))
        except ApiError as e:
            log.debug("appliance health unavailable: %s", e)
        alarms = self._try_list("/api/health/alarms", "alarms")
        if alarms is not None:
            rows = []
            for a in alarms:
                rows.append(dict(
                    id=a["id"], name=a.get("name"), event_key=a.get("eventKey"),
                    status=a.get("status"), severity=a.get("severity") or a.get("status"),
                    resource_name=a.get("resourceName"), ref_type=a.get("refType"),
                    ref_id=ref_id(a.get("refId")), message=a.get("statusMessage") or a.get("message"),
                    acknowledged=a.get("acknowledged"), active=bool(a.get("active", True)),
                    start_date=ts(a.get("startDate")), raw=J(a)))
            self.db.upsert("alarms", rows)
            self.db.execute("UPDATE alarms SET active = false WHERE active AND NOT (id = ANY(%s))",
                            ([a["id"] for a in alarms],))
            active = [a for a in alarms if a.get("active", True)]
            points.append(("summary", 0, "alarms_active", len(active)))
            points.append(("summary", 0, "alarms_unacknowledged",
                           sum(1 for a in active if not a.get("acknowledged"))))
        self.db.write_metrics(t, points)
        self._activity()
        return len(points)

    def _activity(self):
        try:
            j = self.api.get("/api/activity", {"max": 200})
        except ApiError as e:
            log.debug("activity unavailable: %s", e)
            return
        rows = []
        for a in j.get("activity") or []:
            key = str(a.get("_id") or a.get("id") or f"{a.get('ts')}|{a.get('name')}|{a.get('message')}")[:500]
            rows.append(dict(key=key, ts=ts(a.get("ts")) or now(), name=a.get("name"),
                             activity_type=a.get("activityType"), object_type=a.get("objectType"),
                             message=a.get("message"),
                             user_name=a.get("userName") or (a.get("user") or {}).get("username"),
                             success=a.get("success"), raw=J(a)))
        if rows:
            self.db.insert_ignore("activity", rows, "key")

    # ------------------------------------------------------------ inventory
    def inventory(self):
        n = 0
        ping = {}
        for path in ("/api/ping", "/api/whoami"):
            try:
                j = self.api.get(path, auth=path != "/api/ping")
                ping.update(j.get("appliance") or {})
                ping.update({k: v for k, v in j.items() if k in ("buildVersion", "applianceUrl", "setupNeeded")})
            except ApiError as e:
                log.debug("%s: %s", path, e)
        if ping.get("buildVersion"):
            parts = [int(x) for x in re.findall(r"\d+", ping["buildVersion"])[:2]]
            if parts < list(MIN_VERSION):
                log.warning("VME %s is older than the supported %s; some panels may be empty",
                            ping["buildVersion"], ".".join(map(str, MIN_VERSION)))
        if ping:
            self.db.execute(
                "INSERT INTO appliance (id, url, build_version, last_seen, raw) VALUES (1, %s, %s, now(), %s) "
                "ON CONFLICT (id) DO UPDATE SET url = EXCLUDED.url, build_version = EXCLUDED.build_version, "
                "last_seen = now(), raw = EXCLUDED.raw",
                (ping.get("applianceUrl") or self.api.base, ping.get("buildVersion"), J(ping)))

        zones, _ = self.api.list("/api/zones", "zones")
        self.db.upsert("clouds", [dict(
            id=z["id"], name=z.get("name"), type_code=(z.get("zoneType") or {}).get("code"),
            type_name=(z.get("zoneType") or {}).get("name"), status=z.get("status"),
            last_sync=ts(z.get("lastSync")), raw=J(z))
            for z in zones])
        self.db.mark_absent("clouds", [z["id"] for z in zones])
        n += len(zones)

        insts = self._try_list("/api/instances", "instances")
        if insts is not None:
            rows = []
            for i in insts:
                tags = i.get("tags") or []
                rows.append(dict(
                    id=i["id"], name=i.get("name"),
                    instance_type=(i.get("instanceType") or {}).get("name"),
                    layout=(i.get("layout") or {}).get("name"), plan=(i.get("plan") or {}).get("name"),
                    status=i.get("status"), power_state=i.get("powerState"),
                    cloud_id=ref_id(i.get("cloud") or i.get("zone")),
                    owner=(i.get("owner") or {}).get("username"),
                    created_by=(i.get("createdBy") or {}).get("username"),
                    environment=i.get("instanceContext") or i.get("environment"),
                    tags=", ".join(f"{t.get('name')}={t.get('value')}" if isinstance(t, dict) else str(t) for t in tags),
                    server_ids=sorted(ids_from(i.get("servers"))),
                    date_created=ts(i.get("dateCreated")), raw=J(i)))
            self.db.upsert("instances", rows)
            self.db.mark_absent("instances", [i["id"] for i in insts])
            n += len(rows)

        nets = self._try_list("/api/networks", "networks")
        if nets is not None:
            self.db.upsert("networks", [dict(
                id=x["id"], name=x.get("name"), type=(x.get("type") or {}).get("name"),
                cloud_id=ref_id(x.get("zone") or x.get("cloud")), cidr=x.get("cidr"),
                vlan_id=x.get("vlanId"), dhcp=x.get("dhcpServer"), status=x.get("status"),
                raw=J(x)) for x in nets])
            self.db.mark_absent("networks", [x["id"] for x in nets])
            n += len(nets)
        return n
