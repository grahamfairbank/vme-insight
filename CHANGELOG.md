# Changelog

## Unreleased (0.7.0)

* **HPE colors.** The dashboards use colors from the HPE Design System: green `#009a71` for ok, orange `#d36d00` for warnings, red `#ec3331` for critical, blue `#0070f8` for counts and gray `#7d8a92` for off or unknown. Each one reads on both the dark and the light background. Lines that compare several hosts or VMs keep Grafana's own series colors, because Grafana can't be given a different set.
* **HPE backgrounds.** Grafana's dark theme now uses a `#222222` page and panels, and the light theme uses white (`#FFFFFF`). Thin borders separate the panels. This also applies to the dashboards shown in the Morpheus UI. See [DASHBOARDS: Colors and backgrounds](docs/DASHBOARDS.md#colors-and-backgrounds).
* **Appliance: version in the login banner.** The text shown when you sign in to the VM now starts with the installed version, for example `vme-insight appliance 0.7.0: running: …`. After `vme-insight-update` it shows the version that was installed.
* **Cluster storage shows real usage.** The VME Overview gauge, now *Cluster shared storage*, shows how full the cluster's shared datastores are (shared LUNs and NFS, each counted once). It used to add up the storage Morpheus reports per host, which is how much disk is allocated rather than used, and counts shared LUNs once per host, so it read about 98% on a lab whose datastores were 2 to 75% full. The host panels that show Morpheus's per-host figure are renamed *Host disks allocated* to say what it is.
* **HVM clouds only.** When the same HPE Morpheus manages VMware or other clouds as well as HVM (HPE Virtual Machine) clusters, vme-insight now collects only the clouds that hold HVM clusters or hosts. Before, VMware clusters, ESXi hosts, their VMs and datastores showed up in the dashboards next to the HVM ones. A new `clouds.hvm_only` setting in `config.yaml` (default `true`) turns this off. If no HVM cluster or host is found at all, it collects everything and logs a warning. Alarms and the activity log still cover the whole Morpheus appliance.
* **Grafana no longer contacts grafana.com while running.** It used to check for Grafana and plugin updates every 10 minutes, fetch a list of Angular plugin patterns daily, and install a Loki app vme-insight doesn't use. All of that is off now, along with the news feed, plugin signing-key downloads and sharing snapshots to grafana.com. The treemap plugin download on first start of a non-appliance install is unchanged (the appliance ships it). The appliance tests now fail if anything reaches grafana.com.
* **Appliance: more settings in the wizard.** `sudo vme-insight-setup` now asks for time servers, DNS servers, whether to check GitHub daily for a new release, and the database's memory. Time servers are a new `time_servers` setting (no more shell commands); see [APPLIANCE: Your own time servers](docs/APPLIANCE.md#your-own-time-servers). DNS servers are new `dns_servers` and `dns_search` settings that replace the servers from Morpheus or DHCP, such as Morpheus's 8.8.8.8 default, on a VM that's already running; see [APPLIANCE: DNS servers](docs/APPLIANCE.md#dns-servers).
* **Appliance: the database uses memory you add.** TimescaleDB used to keep the tuning from the VM's first boot. Now, at each boot, it's tuned again for a quarter of the VM's memory when that has changed, so adding memory in Morpheus and restarting the VM is enough. A new `database.memory` setting fixes the size instead (for example `4GB`).
* **Bar gauges and pie charts keep their size.** Bar gauges (Top VMs, Running VMs per host, Datastore usage and others) show each name in full above a slim bar with fixed 14 px text, instead of letting Grafana scale the text up until names were cut to "sm…". The empty part of each bar is lighter on the dark theme so it stays visible on `#222222`. Pie chart legends sit below the donut as a list with count and percent, and those panels are a little taller, so the donut no longer shrinks and the legend no longer needs a sideways scrollbar.

## 0.6.1 (2026-11-15)

* **Appliance: https is on by default.** A new appliance serves the dashboards at `https://<vm-address>` (port 443), which the Morpheus UI needs to show them. The wizard's https question now defaults to Yes, and user data without an `https` section turns it on. Plain http on port 3000 stays open unless you close it. Appliances set up before 0.6.1 keep their setting and port, so an update never opens or moves a port by itself.
* **Fixed (appliance): `https://<vm-address>` showed an empty page** when the wizard's "Names and IPs people type" question was left empty: the https front end then answered only for `localhost`. An empty list now means this VM's own IP addresses and host name, found again at each boot. See [APPLIANCE: Names and addresses](docs/APPLIANCE.md#names-and-addresses).
* **Fixed (appliance): `vme-insight-update` didn't update the appliance's own scripts and services** (`vme-insight-setup`, `vme-insight-apply`, `vme-insight-update`), so the 0.6.0 fixes never reached an appliance updated from 0.5.0. It now installs them with each update. **After updating from 0.6.0 or earlier, run once:** `sudo sh /opt/vme-insight/appliance/install-system-files.sh && sudo vme-insight-apply` ([APPLIANCE: Keeping it up to date](docs/APPLIANCE.md#keeping-it-up-to-date)).
* The login message and `sudo vme-insight-setup --status` show the VM's address instead of `<this VM's address>`.

## 0.6.0 (2026-11-14)

* **Appliance: https on port 443.** `vme-insight-setup` now asks which port https uses. A new appliance defaults to 443, so people type `https://vme-insight.example.com` with no port number. An appliance that already has https keeps its port (3443) when you run the wizard again, and user data with `https.enabled: true` but no `https.port` still means 3443. **If you change the port, change the vme-insight plugin's Grafana URL in Morpheus at the same time**, or its tabs show an empty frame. See [APPLIANCE: The https port](docs/APPLIANCE.md#the-https-port).
* **Fixed (appliance):** running `vme-insight-setup` again dropped settings it doesn't ask about, such as your own https certificate, your own CA for Morpheus or the Grafana port. It now keeps them.
* **Fixed (appliance):** every boot reset `/opt/vme-insight/config/config.yaml` to the example, losing hand edits to retention, intervals and lifecycle rules. Only its `morpheus` section is now written from the appliance settings; the rest is kept.
* **Appliance guide** reworked: why Debian, what the owner of the appliance looks after, an internet-access table, the cloud-init user and network address requirements, time servers, and a sizing section with measured figures and a disk formula (4 GB of memory is the minimum); growing the disk later through Morpheus is tested on an HVM cluster. Settings changes go through `sudo vme-insight-setup`. New troubleshooting entry for browsers that send the appliance's address to a corporate proxy.
* **Changing passwords:** new section in [INSTALL](docs/INSTALL.md#changing-passwords) for Grafana's admin user, the two database users and the Morpheus account. It applies to the appliance too.
* Appliance test tools: `MEM` and `CPUS` set the size of the test VM.

## 0.5.0 (2026-11-14)

* **Virtual appliance.** A ready-to-import QCOW2 image for HPE Morpheus VM Essentials, attached to this release: Debian 13 with Docker, vme-insight and all its container images inside, so it runs without internet access. Settings arrive through the image's cloud-init user data or the `sudo vme-insight-setup` wizard, including an optional HTTP(S) proxy (the connection to Morpheus always stays direct). Passwords are generated on each VM at first boot, and nothing secret is baked into the image. Tested in a lab Morpheus on an HVM cluster with a GFS2 datastore (no NFS needed), with DHCP and with a static address. See [APPLIANCE](docs/APPLIANCE.md).
* **Appliance updates.** `sudo vme-insight-update` updates vme-insight and its container images from the latest GitHub release after you confirm (take a VM snapshot first), keeping settings and data. A daily read-only check shows "update available" in the login message. Debian itself is patched like any Debian server, with your usual method.
* **Manager sizing against both HPE guides.** The "Manager size: Essentials and Enterprise" panel (was "Manager size vs HPE recommendation") gives a result for each guide. **VM Essentials:** which VME manager profile the manager matches (Small is 12 GB RAM and 2 vCPUs; HPE doesn't publish Medium and Large values or a disk size). **Morpheus Enterprise:** whether it meets the appliance requirements (4 cores, 16 GB, 200 GB). Previously only the Enterprise figures were used, so a correctly sized VME manager showed as "below". The manager disk guidance drops the 200 GB figure, which applies to Enterprise only.
* Docs, dashboards and diagrams in US English ("color", "organization", "center"); screenshots and architecture PDFs regenerated. Compatibility rows for plugins 0.1.4 and 0.1.5.
* Screenshot tool: a warm-up load before the first capture, which could be taken before its panels had drawn.

## 0.4.5 (2026-10-23)

* VME-PLUGIN certificate guide: switching away from the built-in CA (remove its old root), getting the certificate to browser machines via the installer service, step 4 errors for untrusted certificates, name mismatch and browsing by IP, and a Removing step that matches the current certificate options.
* **Fixed:** RHEL-family guests (Rocky, RHEL, Alma, Oracle) could get the wrong OS release, because VME reports their kernel version (e.g. `6.12.0-…el10_2…`) as the platform version: Rocky Linux 10 showed as release 6. The OS version now comes from the kernel's `elN_M` marker or the OS name, so end-of-life and update status are right.
* Docs: [RELEASING](docs/RELEASING.md), the release standard shared with vme-insight-plugin; [DEVELOPMENT](docs/DEVELOPMENT.md) for changing dashboards, the collector and the docs; compatibility rows for plugin 0.1.3.
* Full deinstallation removes only images vme-insight built (`--rmi local`), keeping shared public images other projects may use; the docs say exactly what is and isn't removed.
* `vmeinsight.tlsinfo` prints the `tls_fingerprint:` line ready to paste into `config.yaml` (no leading `#`, which made YAML ignore the line). The install guide says to copy that line from the command's output, shows where it goes, and makes the independent fingerprint check clearly optional.

## 0.4.4 (2026-10-23)

* **A database password mismatch is explained instead of waited on.** When `DB_PASSWORD` doesn't match the existing database (typically a reinstall or fresh clone reusing the old volume), the collector says so, with the three ways to fix it, and exits, instead of logging "waiting for database" forever.
* Docs: [reinstalling or starting over](docs/INSTALL.md#reinstalling-or-starting-over) (volumes outlive the checkout and keep their passwords); troubleshooting for the database and Grafana admin password.

## 0.4.3 (2026-10-23)

* **Rejected logins are handled safely.** A wrong VME username or password now gives one clear message (what to check, including YAML quoting) instead of a traceback per task, and the collector waits 15 minutes before trying again, so it can't lock the account by retrying. A rejected API token gets its own message.
* The collector refuses a `username`, `password` or `api_token` that YAML has read as a number or true/false (e.g. an unquoted `012345` losing its leading zero), and says to quote it.
* Troubleshooting: Docker socket permission denied (fresh installs, apt and snap); rejected logins with a credential test that keeps the password out of shell history.

## 0.4.2 (2026-10-22)

* **Fixed:** browsing to the https front end by IP (`https://<ip>:3443`) failed with `ERR_SSL_PROTOCOL_ERROR`: browsers send no server name for an IP, and behind Docker the front end couldn't tell which address was used. New `HTTPS_DEFAULT_SNI`: set it to that IP (and list the IP in `HTTPS_HOSTNAME` and the certificate). Unset, behavior is unchanged.
* Troubleshooting: an https front end section (protocol error, untrusted certificate, name mismatch, 403).

## 0.4.1 (2026-10-22)

* **Fixed:** the collector failed with `PermissionError: /config/config.yaml` when the config file belonged to another user (e.g. installed as root) with mode 600, as the install guide recommends. The container now starts as root only to copy the config into a private `/config`, then drops to uid 1000 with no capabilities and no-new-privileges. `docker-compose.yml` mounts `./config` at `/config-src`; rebuild the collector after upgrading.

## 0.4.0 (2026-10-21)

* **VM resource weight treemaps** on the Overview: CPU, allocated memory and storage share per VM, labeled with the share. Uses the Treemap panel by Grafana Labs (`marcusolsson-treemap-panel` 2.1.1, signed, pinned), installed by Grafana on first start; `GRAFANA_PLUGINS` and [offline installs](docs/INSTALL.md#offline-installs) documented.
* Screenshot tool blurs only the sensitive part of a label (names inside longer text stay hidden while the rest stays readable), including SVG labels.
* **Safer certificates for the https front end.** New `tools/make-cert.sh`: a self-signed certificate for this host only (`CA:FALSE`), or a private CA limited by name constraints to your domain and network, with every `openssl` command printed (`--dry-run` to only print). The certificate docs now rank the options from least to most new trust (your organization's CA, a public certificate, `make-cert.sh host`, `make-cert.sh ca`, the built-in CA as a lab shortcut), explain the built-in CA's risks, and add a fingerprint check before importing, per-account import as the default, and how to remove trust.

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
