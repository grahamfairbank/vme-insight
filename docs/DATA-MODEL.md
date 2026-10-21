# Data model

Everything the collector gathers is in one PostgreSQL database (`vme`) with the TimescaleDB extension. Grafana reads it as the read-only user `grafana_ro`, so any panel you build can use plain SQL.

To open a SQL shell:

```bash
docker compose exec timescaledb psql -U vme -d vme
```

The schema is in [`collector/vmeinsight/schema.sql`](../collector/vmeinsight/schema.sql). The collector applies it at every start, and every statement is idempotent.

## Time series: `metrics`

One row per sample:

| Column | Type | Example |
|---|---|---|
| `time` | timestamptz | `2026-10-21 13:38:46+00` |
| `entity_type` | text | `host`, `vm`, `cluster`, `datastore`, `appliance`, `summary` |
| `entity_id` | bigint | VME id (`servers.id`, `clusters.id`, `datastores.id`). `0` for appliance and summary. |
| `metric` | text | `cpu_pct` |
| `value` | double | `27.3` |

This "narrow" layout means new metrics need no schema change. It's a hypertable with 1-day chunks, compressed after `retention.compress_after` days and dropped after `retention.raw` days.

`metrics_hourly` is a continuous aggregate with columns `bucket`, `entity_type`, `entity_id`, `metric`, `avg`, `min`, `max` and `samples`. It refreshes every 30 minutes and is kept for `retention.hourly` days. Use it for ranges longer than the raw retention.

### Metric catalogue

**host** and **vm** (from `/api/servers`, every minute):

| Metric | Unit | Notes |
|---|---|---|
| `cpu_pct` | % | CPU usage |
| `cpu_ready_pct` | % | Time vCPUs waited for a physical CPU, averaged across the VM's vCPUs |
| `cpu_ready_max_vcpu_pct` | % | VMs: the worst single vCPU (from VME's per-vCPU values) |
| `mem_used_bytes`, `mem_free_bytes`, `mem_total_bytes`, `mem_pct` | bytes, % | |
| `mem_reserved_bytes` | bytes | Memory reserved for the VM, or by VMs on a host |
| `storage_used_bytes`, `storage_total_bytes`, `storage_reserved_bytes`, `storage_pct` | bytes, % | Host: local storage. VM: its disks. |
| `net_rx`, `net_tx` | bytes/s as reported | |
| `disk_iops`, `disk_read_iops`, `disk_write_iops` | IOPS | |
| `swap_used_bytes`, `swap_free_bytes` | bytes | Hosts |
| `cores` | count | Host cores / VM vCPUs |
| `up` | 0/1 | Powered on |
| `guest_agent_connected` | 0/1 | VMs, QEMU guest agent |
| `vm_count`, `vm_running` | count | Hosts |
| `raw.<field>` | | Every other numeric field VME returns in `stats`, kept as-is (for example `raw.cpuReadyVcpu0`, `raw.bandwidth`) |

Stopped servers keep only capacity metrics, because VME keeps reporting their last live values.

**cluster** (computed from its hosts each minute): `cpu_pct` (host average), `mem_used_bytes`, `mem_total_bytes`, `mem_pct`, `storage_used_bytes`, `storage_total_bytes`, `storage_pct`, `net_rx`, `net_tx`, `cores`, `host_count`, `vm_count`, `vm_running`. VME's own cluster figures are kept as `raw.worker.*`.

**datastore** (every 5 minutes): `capacity_bytes`, `free_bytes`, `used_bytes`, `used_pct`, `online`.

**appliance** (the VME manager, every 5 minutes): `cpu.*`, `memory.*` (for example `memory.memoryPercent` = JVM heap %, `memory.systemMemoryPercent` = VM memory %; VME reports these as fractions and the collector stores them as percentages), `storage.total|used|available|percent`, `storage.fs.<path>.percent|used|available|total` per filesystem, `database.usedConnections|maxConnections|maxUsedConnections|busyConnections|abortedConnections`, `elastic.<node>.heapPercent|ramPercent|loadOne|loadFive`, `rabbit.queued_messages|busy_queues|error_queues`, `rabbit.queue.<name>` (non-empty queues only), `threads.busy`, `service.<name>.ok` (1/0). The full health document is kept in `appliance.health`.

**summary** (estate totals): `hosts_total`, `hosts_on`, `vms_total`, `vms_on`, `vms_off`, `clusters_total`, `alarms_active`, `alarms_unacknowledged`.

## Inventory tables

Each table has `present` (still returned by VME), `first_seen`, `last_seen` and `raw` (the full API object as JSON, so any field VME returns can be queried even if it has no column).

| Table | One row per | Main columns |
|---|---|---|
| `servers` | Host or VM | `kind` (`host`/`vm`), `name`, `cluster_id`, `host_id` (VMs), `power_state`, `status`, `ip_internal`, `os_name`, `platform`, `platform_version`, `os_product`, `os_cycle`, `os_version_full`, `agent_installed`, `agent_version`, `agent_last_update`, `guest_agent_status`, `max_cores`, `max_memory`, `max_storage`, `maintenance`, `member_status`, `cpu_model`, `hw_vendor`, `hw_model`, `plan`, `source_image`, `type_code` |
| `clusters` | Cluster | `name`, `type_name`, `layout` (e.g. "HVM 2.0 Cluster on HVM/Ubuntu 26.04"), `status`, `host_ids` |
| `clouds` | Cloud | `name`, `type_name`, `status`, `last_sync` |
| `datastores` | Datastore | `name`, `type` (e.g. "HPE Clustered Datastore (Shared LUN)", "NFS Datastore"), `status`, `capacity_bytes`, `free_bytes` |
| `instances` | Instance | `name`, `instance_type`, `layout`, `plan`, `status`, `owner`, `created_by`, `tags`, `server_ids` |
| `networks` | Network | `name`, `type`, `cidr`, `vlan_id`, `dhcp` |
| `alarms` | Alarm | `name`, `severity`, `resource_name`, `ref_type`, `ref_id`, `message`, `acknowledged`, `active`, `start_date` |
| `activity` | Activity entry | `ts`, `activity_type`, `object_type`, `name`, `message`, `user_name`, `success` |
| `appliance` | (one row) | `url`, `build_version`, `health` (JSON), `health_at` |
| `inventory_changes` | Field change | `time`, `entity_type`, `entity_id`, `name`, `field`, `old_value`, `new_value` |
| `os_lifecycle` | OS release cycle | `product`, `cycle`, `release_date`, `support_date`, `eol_date`, `latest`, `lts` |
| `collector_runs` | Collector task run | `time`, `task`, `ok`, `duration_ms`, `items`, `error` (30 days) |

Views: `entity_names` (a name for every `entity_type`/`entity_id` in `metrics`), `server_currency` (one row per present server with OS and agent status, see [LIFECYCLE](LIFECYCLE.md)) and `agent_target`. The function `version_key(text)` turns a version string into a comparable number array.

## Example queries

Average and peak CPU per host over the last 7 days:

```sql
SELECT s.name, round(avg(m.value)::numeric, 1) AS avg_cpu, round(max(m.value)::numeric, 1) AS peak_cpu
FROM metrics m JOIN servers s ON s.id = m.entity_id
WHERE m.entity_type = 'host' AND m.metric = 'cpu_pct' AND m.time > now() - INTERVAL '7 days'
GROUP BY s.name ORDER BY avg_cpu DESC;
```

VMs that used less than 5% CPU at peak over 30 days (right-sizing candidates), from the hourly rollup:

```sql
SELECT s.name, s.max_cores, max(h.max) AS peak_cpu
FROM metrics_hourly h JOIN servers s ON s.id = h.entity_id
WHERE h.entity_type = 'vm' AND h.metric = 'cpu_pct' AND h.bucket > now() - INTERVAL '30 days' AND s.present
GROUP BY s.name, s.max_cores HAVING max(h.max) < 5 ORDER BY s.max_cores DESC;
```

Datastore growth per day over the last 30 days:

```sql
SELECT d.name, (last(h.avg, h.bucket) - first(h.avg, h.bucket)) / 30 AS bytes_per_day
FROM metrics_hourly h JOIN datastores d ON d.id = h.entity_id
WHERE h.entity_type = 'datastore' AND h.metric = 'used_bytes' AND h.bucket > now() - INTERVAL '30 days'
GROUP BY d.name ORDER BY 2 DESC;
```

VM live migrations this week:

```sql
SELECT c.time, c.name, h1.name AS from_host, h2.name AS to_host
FROM inventory_changes c
LEFT JOIN servers h1 ON h1.id = c.old_value::bigint LEFT JOIN servers h2 ON h2.id = c.new_value::bigint
WHERE c.field = 'host_id' AND c.time > now() - INTERVAL '7 days' ORDER BY c.time DESC;
```

Any field VME returns, through `raw`:

```sql
SELECT name, raw->>'hardwareCpuModel' AS cpu, raw->'stats'->>'bandwidth' AS nic_mbps
FROM servers WHERE kind = 'host';
```

## Adding or changing panels

* **Quick:** in Grafana, open a dashboard, **Add → Visualization**, choose the **VME TimescaleDB** data source, switch the query editor to **Code** and write SQL. Time series queries return `time`, `metric` (series name) and `value`:

  ```sql
  SELECT $__timeGroupAlias(m.time, $__interval), s.name AS metric, avg(m.value) AS value
  FROM metrics m JOIN servers s ON s.id = m.entity_id
  WHERE $__timeFilter(m.time) AND m.entity_type = 'host' AND m.metric = 'swap_used_bytes'
  GROUP BY 1, 2 ORDER BY 1
  ```

  Save the dashboard as a copy so provisioning doesn't overwrite it.

* **Permanent / to contribute:** edit [`tools/build_dashboards.py`](../tools/build_dashboards.py). Helpers such as `series()`, `latest_metric()`, `timeseries()`, `table()` and `bargauge()` keep panels short. Then run:

  ```bash
  python3 tools/build_dashboards.py      # regenerate grafana/dashboards/*.json
  python3 tools/check_dashboards.py      # run every query against the live Grafana
  ```

* **New metric from the API:** add it to `CANONICAL` in [`collect.py`](../collector/vmeinsight/collect.py). Until then it's already stored as `raw.<field>`.

## Sizing

Each host or VM writes about 30 metrics a minute, about 43,000 rows a day. The last `compress_after` days (7) stay uncompressed at roughly 100 bytes a row. Older data is compressed, typically to under 10 bytes a row.

| Servers (hosts + VMs) | Uncompressed week | 90 days compressed | Total at defaults |
|---|---|---|---|
| 10 | ~0.3 GB | ~0.3 GB | ~0.6 GB |
| 100 | ~3 GB | ~3 GB | ~6 GB |
| 1,000 | ~30 GB | ~30 GB | ~60 GB |

Hourly rollups add little (one row per metric per hour). To use less disk, lower `retention.raw` (the hourly rollups keep the long view) or `retention.compress_after`. The **Database size** panel on the Manager & Collector dashboard shows actual use. Measure it after a week rather than relying on these estimates.
