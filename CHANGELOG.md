# Changelog

## 0.3.0 (2026-10-21)

* New Overview tiles: **VM disk size** (median and average provisioned disk per VM) and **Idle VMs** (running VMs whose CPU never went above 5% in 24 hours; VME reports about 2% even for an idle VM, so the threshold sits above that), with an idle-candidates list on the VMs dashboard.
* Screenshots refreshed.

## 0.2.0 (2026-10-21)

Support for showing the dashboards inside VME with the companion [vme-insight-plugin](https://github.com/grahamfairbank/vme-insight-plugin). Everything is optional; defaults are unchanged.

* Optional https front end (`--profile https`, Caddy) with a network allowlist (`HTTPS_ALLOW`), its own certificate authority or your certificate (`HTTPS_TLS`), and `HTTPS_LOG_LEVEL` for troubleshooting.
* Optional anonymous read-only viewing (`GRAFANA_ANONYMOUS`), `GRAFANA_BIND` to keep Grafana's own port on the Docker host, `GRAFANA_ROOT_URL`, `GRAFANA_COOKIE_SECURE`.
* New **VME Summary tiles** dashboard (`vme-widget`) with fixed panel ids for embedding single tiles.
* New guide [VME-PLUGIN](docs/VME-PLUGIN.md): end-to-end setup for the plugin, including trusting the certificate on Windows with PowerShell.

## 0.1.0

First version.

* Collector for the VME 9.1+ API: hosts, VMs, clusters, datastores, clouds, instances, networks, alarms, activity, manager health.
* TimescaleDB storage with compression, hourly rollups and retention; inventory tables with a change log.
* OS end-of-life and update status from endoflife.date; Morpheus agent and QEMU guest agent status.
* TLS certificate pinning for self-signed managers; http:// URLs upgraded to https://.
* Optional node and libvirt exporters on HVM hosts, with Prometheus targets discovered from the API.
* Eight provisioned Grafana dashboards.
* Host filesystem monitoring: per-mount space, inodes, days to full and read-only state (node_exporter), plus VME's per-host storage total.
* Manager resource monitoring: disk used, free and days until full, filesystem table, memory and swap, with Elasticsearch-aware disk guidance; optional node_exporter inside the manager VM.
* Host filesystem panels show VME datastore names (collector publishes `vme_datastore_info` / `vme_vm_info` to Prometheus).
* Exporter installer runs on the host (`curl … | sudo bash` from the optional installer service), doesn't use apt (HVM hosts use HPE repositories), pins SHA-256 for both downloads.
* Fixed: manager memory percentages were shown as fractions.
* README tour with screenshots (server names and IPs blurred in the browser before capture, data unedited) and `tools/screenshots.py` to regenerate them; community-project disclaimer.
* Fixed: the VME manager's node_exporter was counted as an HVM host on the exporter dashboards.
* Manager "days until disk full" waits for a day of history instead of extrapolating from a few hours.
* CSV exports: a **VME Data Export** dashboard (metric samples, hourly rollups, inventory, changes, alarms, activity, raw API records) and `tools/export_csv.py` for unlimited command-line exports.
* Hourly rollups use real-time aggregation, so they include the current hour.
* Thresholds aligned with HPE's VME documentation: VME's default alarm levels (CPU 85/95%, memory 90/95%, datastores 80/90%), agent check-in age (2/5 min), cluster memory capacity (70%), manager disk (85%).
* New: N+1 failover headroom per cluster, manager size vs HPE's recommendation, CPU overcommit guidance.
* Docs: corrected reader-role permission names, retention settings and token expiry; added references to HPE's documentation (HewlettPackard/morpheus-docs).
* CPU ready guidance on every CPU ready panel (thresholds in titles, shaded bands, full table in the info tooltip), CPU contention tiles on the Overview, and a worst-single-vCPU metric.
