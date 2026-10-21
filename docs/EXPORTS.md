# CSV exports

Two ways to get vme-insight data out for investigation, a spreadsheet, a ticket or another tool:

| | Grafana: **VME Data Export** dashboard | Command line: `tools/export_csv.py` |
|---|---|---|
| Best for | Quick, interactive pulls while investigating | Large pulls: weeks of per-minute data, the whole estate |
| Size | Up to 200,000 rows per table | Unlimited (streamed from the database) |
| Needs | A Grafana login (Viewer is enough) | Shell access on the vme-insight host |

Both read the same data: metric samples (raw for `retention.raw` days, default 90), hourly rollups (default 2 years), current inventory, and the change, alarm and activity history.

## In Grafana: VME Data Export

Open **VME Data Export** from the **VME dashboards** menu. Choose what to export with the variables at the top and the time range at the top right. Every panel follows them.

| Variable | Meaning |
|---|---|
| **Kind** | `host`, `vm`, `cluster`, `datastore`, `appliance` (the VME manager) or `summary` (estate totals) |
| **Entity** | One or more objects of that kind, or All |
| **Metric** | One or more metrics (only those collected for that kind in the last 2 days are listed), or All. See the [metric catalogue](DATA-MODEL.md#metric-catalogue). |
| **Resolution** | Bucket size for metric samples: 1 minute to 1 day. Each bucket gives avg, min, max and the number of samples. |

Panels:

| Panel | Contents |
|---|---|
| Metric samples (long format) | One row per time bucket, entity and metric: `time, kind, entity, entity_id, metric, avg, min, max, samples` |
| One column per entity | The same data as a chart. Its CSV, with *Series joined by time*, has one column per entity and metric, which is easiest to chart in a spreadsheet. |
| Hourly rollups | Hourly avg/min/max from the long-term rollups. Use it for ranges older than the raw retention. Includes the current hour. |
| Hosts and VMs | Every current host and VM: placement, size, IPs, OS, release cycle, end-of-life status, agent versions and status, guest agent, hardware, plan, image, first and last seen |
| Datastores | Type, status, cluster, capacity, free, used, used %, and the path where hosts mount it |
| Clusters, instances and networks | Other current inventory objects |
| Inventory changes | Every change to hosts and VMs in the time range (discovered, removed, power, OS, agent, resize, migration and more) |
| Alarms | Alarms that were open at any point in the time range |
| Activity | VME's activity feed in the time range |
| Raw API record | Every field VME returned for one object (secrets redacted), as `field, value`. For the manager it's the `/api/health` document. Handy when a dashboard value looks wrong, or to find fields that have no column yet. |

### Downloading

1. Hover the panel, open its menu (⋮) and choose **Inspect → Data**.
2. Set the options:
   * **Formatted data** off: raw numbers (bytes, percentages as plain numbers). Best for spreadsheets and scripts. On: values with units, as shown on screen.
   * **Download for Excel**: adds the byte-order mark Excel needs to show non-ASCII names correctly.
   * For the *One column per entity* panel, set **Data options → Series joined by time**.
3. Click **Download CSV**.

Any panel on any vme-insight dashboard can be exported the same way. The export dashboard just lays the data out in the most useful shape.

Timestamps are exported in the dashboard's time zone (your browser's, by default). To get UTC, set the dashboard time zone to UTC first (time picker → *Change time settings*).

## Command line: tools/export_csv.py

Run it on the vme-insight host from the repo directory. It streams CSV straight from TimescaleDB, so there's no row limit. Times are UTC.

```bash
# what can be exported for a kind
tools/export_csv.py metrics --kind host --list-metrics

# host CPU and memory for the last 7 days in 5-minute buckets
tools/export_csv.py metrics --kind host --metric cpu_pct --metric mem_pct --since 7d --res 5m -o hosts.csv

# every raw sample of two VMs between two dates
tools/export_csv.py metrics --kind vm --entity web01 --entity web02 --from 2026-10-01 --to 2026-10-15 --res raw -o vms.csv

# a year of datastore usage from the hourly rollups
tools/export_csv.py metrics --kind datastore --metric used_pct --since 365d --source hourly -o datastores-year.csv

# inventory and history
tools/export_csv.py inventory -o inventory.csv
tools/export_csv.py datastores
tools/export_csv.py changes --since 30d -o changes.csv
tools/export_csv.py alarms --since 30d
tools/export_csv.py activity --since 30d
```

| Option | Meaning |
|---|---|
| `--kind` | `host`, `vm`, `cluster`, `datastore`, `appliance`, `summary` (default `host`) |
| `--entity NAME` | Repeat for several. Default: all of that kind. Names as shown in VME. |
| `--metric NAME` | Repeat for several. Default: all. |
| `--since` | `30m`, `12h`, `7d`, `4w` before now (default `24h`) |
| `--from`, `--to` | ISO date or time, e.g. `2026-10-01` or `2026-10-01T08:00`. UTC unless an offset is given. `--to` defaults to now. |
| `--res` | `raw`, `1m`, `5m`, `15m`, `1h`, `1d` (default `5m`). Buckets give `avg, min, max, samples`. |
| `--source hourly` | Read the hourly rollups instead of raw samples, for ranges beyond the raw retention |
| `-o FILE` | Write to a file (prints the row count); otherwise CSV goes to stdout, so it can be piped |

Columns match the Grafana export panels, so files from either source line up.

The tool runs `psql` inside the `timescaledb` container through `docker compose`, so it needs the same access as `docker compose ps`. Names and metrics you pass reach the database only as bound psql variables, never as SQL text.

## Writing your own query

Anything in [DATA-MODEL](DATA-MODEL.md) can be exported with plain SQL:

```bash
docker compose exec -T timescaledb psql -U vme -d vme -c \
  "COPY (SELECT name, os_status, eol_date FROM server_currency ORDER BY eol_date) TO STDOUT WITH (FORMAT csv, HEADER)" > eol.csv
```
