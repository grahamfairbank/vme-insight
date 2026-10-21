# Configuration

There are two files:

* **`.env`**: settings for the stack (passwords, ports, retention of exporter data). Read by Docker Compose.
* **`config/config.yaml`**: settings for the collector (VME connection, intervals, retention, lifecycle). Mounted read-only into the collector at `/config/config.yaml`.

Both hold secrets. Keep them `chmod 600` and out of git (`.gitignore` already excludes them).

## .env

| Variable | Default | Meaning |
|---|---|---|
| `DB_PASSWORD` | *required* | Password of the `vme` database owner (used by the collector) |
| `GRAFANA_DB_PASSWORD` | *required* | Password of `grafana_ro`, a read-only database user the collector creates for Grafana |
| `GRAFANA_ADMIN_USER` | `admin` | Grafana admin login |
| `GRAFANA_ADMIN_PASSWORD` | *required* | Grafana admin password (only applied when Grafana's volume is first created; change it in the UI afterwards) |
| `GRAFANA_PORT` | `3000` | Host port for Grafana |
| `GRAFANA_BIND` | `0.0.0.0` | Address Grafana's port is published on. `127.0.0.1` keeps it to the Docker host, so other machines must come through the [https front end](#https-front-end). |
| `GRAFANA_ALLOW_EMBEDDING` | `false` | Allow Grafana pages in iframes (for example inside a VME UI plugin) |
| `GRAFANA_ANONYMOUS` | `false` | Let anyone who can reach Grafana view dashboards without signing in, as a read-only Viewer. Only together with `GRAFANA_BIND=127.0.0.1` and the https front end's network allowlist. See [SECURITY](SECURITY.md#anonymous-viewers). |
| `GRAFANA_ANONYMOUS_ORG` | `Main Org.` | Grafana organisation anonymous viewers see. Must match its name exactly. |
| `GRAFANA_ROOT_URL` | *(blank)* | Grafana's public address, e.g. `https://vme-insight.example.com:3443/`. Set it when using the https front end. |
| `GRAFANA_COOKIE_SECURE` | `false` | `true` once Grafana is only reached over https |
| `HTTPS_PORT` | `3443` | Host port of the https front end |
| `HTTPS_HOSTNAME` | `localhost` | Name(s) users type for Grafana, space-separated; the certificate is issued for these |
| `HTTPS_ALLOW` | `127.0.0.1/32` | Networks allowed through the https front end, space-separated CIDRs (quote the value). Everyone else gets 403. |
| `HTTPS_LOG_LEVEL` | `INFO` | `DEBUG` logs every request and failed TLS handshakes, for troubleshooting |
| `HTTPS_TLS` | `internal` | `internal` issues certificates from the front end's own CA. Or `/certs/<cert>.pem /certs/<key>.pem` for your own certificate in `https/certs/`. |
| `DB_MEMORY` | `1GB` | Memory TimescaleDB tunes itself for on first start |
| `PROM_RETENTION` | `90d` | How long Prometheus keeps exporter data |
| `TZ` | `UTC` | Time zone for collector logs. Dashboards use the browser's time zone. |

### https front end

An optional Caddy service (`--profile https`, configured by `https/Caddyfile`) that serves Grafana over https, and only to the `HTTPS_ALLOW` networks. It's needed to show Grafana inside https pages, such as VME's with the vme-insight VME plugin; browsers block http frames inside https pages. The `HTTPS_*` and `GRAFANA_*` settings above control it.

The step-by-step setup, including how to make browsers trust the certificate, is in **[VME-PLUGIN](VME-PLUGIN.md)**.

To see why a browser can't connect, start the front end with `HTTPS_LOG_LEVEL=DEBUG docker compose --profile https up -d https` and read `docker compose --profile https logs https`. `tls: unknown certificate` means that browser doesn't trust the certificate yet. Restart it without the variable afterwards.

## config.yaml

### morpheus

| Key | Default | Meaning |
|---|---|---|
| `url` | *required* | Manager URL, for example `https://vme-manager.example.com` |
| `username`, `password` | | Reader account (see [INSTALL](INSTALL.md#1-create-a-reader-account-in-vme)) |
| `api_token` | | Use instead of username/password. Tokens expire per the OAuth client's validity interval ([OAuth clients](https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/administration/settings/clients.rst)). |
| `client_id` | `morph-api` | OAuth client. Leave as is for VME. |
| `allow_http` | `false` | Allow `http://` URLs. Without this, `http://` is upgraded to `https://`. |
| `tls_fingerprint` | | SHA-256 fingerprint to pin. See [TLS](#tls). |
| `ca_bundle` | | Path inside the container to a CA file, e.g. `/config/vme-ca.pem` |
| `insecure` | `false` | Skip certificate verification entirely |
| `timeout` | `30` | Seconds per API request |
| `page_size` | `250` | Items per API page. Lists are always read to the end, so this only changes the number of requests. |

Environment overrides: `VME_URL`, `VME_USERNAME`, `VME_PASSWORD`, `VME_API_TOKEN`, `VME_TLS_FINGERPRINT`, `VME_CA_BUNDLE`, `VME_INSECURE`. These are useful with Docker secrets or a vault agent. Add them under the collector's `environment:` in a `docker-compose.override.yml`.

### TLS

VME ships with a self-signed certificate. The collector supports three ways to trust it, checked in this order:

VME generates a self-signed certificate at install; HPE's [SSL Certificates](https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/getting_started/additional/morpheusSslCerts.rst) page covers replacing it with a CA-signed one.

1. **`tls_fingerprint`** (recommended for self-signed). The collector accepts only a certificate with exactly this SHA-256 fingerprint. This protects against impersonation as well as full CA validation does. Get the value with `docker compose run --rm collector python -m vmeinsight.tlsinfo`. Re-pin when the certificate is renewed: the collector then fails with a fingerprint mismatch error, which is intended.
2. **`ca_bundle`**. Use this when the manager has a certificate issued by your own CA. Put the CA's PEM file in `config/` and set `ca_bundle: /config/your-ca.pem`. The hostname in `url` must match the certificate.
3. **`insecure: true`**. No verification. Only for a lab you control.

With none of these set, the certificate must chain to a public CA, as for any normal HTTPS site.

### intervals (seconds)

| Key | Default | Collects |
|---|---|---|
| `metrics` | `60` | Hosts, VMs, clusters (performance and inventory) |
| `storage` | `300` | Datastores |
| `health` | `300` | Alarms, manager health, activity feed |
| `inventory` | `900` | Clouds, instances, networks, manager version |
| `lifecycle` | `86400` | OS lifecycle data from endoflife.date |

VME itself samples host and VM statistics about once a minute, so polling faster than 60 seconds stores duplicates.

### retention (days)

| Key | Default | Meaning |
|---|---|---|
| `raw` | `90` | Per-minute samples |
| `hourly` | `730` | Hourly avg/min/max rollups (`metrics_hourly`) |
| `compress_after` | `7` | Compress raw data older than this (about 90% smaller) |

Changes apply when the collector restarts.

### classification

The collector decides whether a server is a hypervisor host or a VM from its `computeServerType`. HVM hosts are `mvmHost`. If your estate has a type it gets wrong, list the codes here:

```yaml
classification:
  host_type_codes: [myCustomHost]
  vm_type_codes: [someAppliance]
```

The code for each server is in the `type_code` column of the `servers` table.

### lifecycle

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Fetch lifecycle data |
| `api` | `https://endoflife.date` | Lifecycle API (mirror it if the collector has no internet access) |
| `expected_agent_version` | `""` | Morpheus agent version to treat as current. Blank = the newest version seen in the estate. |
| `extra_products` | `[]` | Extra endoflife.date product ids to fetch |
| `os_rules` | `[]` | Extra OS matching rules, checked before the built-in ones |

`os_rules` example, for golden images whose OS string doesn't say what they are:

```yaml
lifecycle:
  os_rules:
    - match: "corp-base-2024"        # regex on OS name / platform text
      product: rhel                  # endoflife.date product id
      cycle: "rhel-?(\\d+)"          # regex; first group is the release cycle
```

The **Unrecognised OS strings** panel on the Lifecycle dashboard lists what needs a rule. See [LIFECYCLE](LIFECYCLE.md).

### exporters

| Key | Default | Meaning |
|---|---|---|
| `enabled` | `true` | Write Prometheus target files for discovered HVM hosts |
| `address` | `internal` | Host field to scrape: `internal` (internal IP), `external` or `hostname` |
| `node_port` | `9100` | node_exporter port |
| `libvirt_port` | `9177` | libvirt exporter port |
| `source` | `vme` | Value of the `source` label on every exporter series, to tell several estates apart in one Prometheus |
| `manager_address` | `""` | Where to scrape node_exporter on the VME manager. Blank = the host in `morpheus.url`. |

### log_level

`INFO` (default) or `DEBUG`. `DEBUG` also logs skipped endpoints.
