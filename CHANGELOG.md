# Changelog

## 0.4.3 (2026-10-23)

* **Rejected logins are handled safely.** A wrong VME username or password now gives one clear message (what to check, including YAML quoting) instead of a traceback per task, and the collector waits 15 minutes before trying again, so it can't lock the account by retrying. A rejected API token gets its own message.
* The collector refuses a `username`, `password` or `api_token` that YAML has read as a number or true/false (e.g. an unquoted `012345` losing its leading zero), and says to quote it.
* Troubleshooting: Docker socket permission denied (fresh installs, apt and snap); rejected logins with a credential test that keeps the password out of shell history.

## 0.4.2 (2026-10-22)

* **Fixed:** browsing to the https front end by IP (`https://<ip>:3443`) failed with `ERR_SSL_PROTOCOL_ERROR`: browsers send no server name for an IP, and behind Docker the front end couldn't tell which address was used. New `HTTPS_DEFAULT_SNI`: set it to that IP (and list the IP in `HTTPS_HOSTNAME` and the certificate). Unset, behaviour is unchanged.
* Troubleshooting: an https front end section (protocol error, untrusted certificate, name mismatch, 403).

## 0.4.1 (2026-10-22)

* **Fixed:** the collector failed with `PermissionError: /config/config.yaml` when the config file belonged to another user (e.g. installed as root) with mode 600, as the install guide recommends. The container now starts as root only to copy the config into a private `/config`, then drops to uid 1000 with no capabilities and no-new-privileges. `docker-compose.yml` mounts `./config` at `/config-src`; rebuild the collector after upgrading.

## 0.4.0 (2026-10-21)

* **VM resource weight treemaps** on the Overview: CPU, allocated memory and storage share per VM, labelled with the share. Uses the Treemap panel by Grafana Labs (`marcusolsson-treemap-panel` 2.1.1, signed, pinned), installed by Grafana on first start; `GRAFANA_PLUGINS` and [offline installs](docs/INSTALL.md#offline-installs) documented.
* Screenshot tool blurs only the sensitive part of a label (names inside longer text stay hidden while the rest stays readable), including SVG labels.
* **Safer certificates for the https front end.** New `tools/make-cert.sh`: a self-signed certificate for this host only (`CA:FALSE`), or a private CA limited by name constraints to your domain and network, with every `openssl` command printed (`--dry-run` to only print). The certificate docs now rank the options from least to most new trust (your organisation's CA, a public certificate, `make-cert.sh host`, `make-cert.sh ca`, the built-in CA as a lab shortcut), explain the built-in CA's risks, and add a fingerprint check before importing, per-account import as the default, and how to remove trust.

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
