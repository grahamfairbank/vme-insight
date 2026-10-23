# Install

This takes about 15 minutes. Steps 1 to 6 give you every dashboard except the three exporter ones. Step 7 is optional.

Tested with: VME 9.1.0.1, HVM 2.0 clusters on Ubuntu 26.04, Docker 29.1, Compose 2.40, TimescaleDB 2.17.2 (PostgreSQL 16), Grafana 11.5.2, Prometheus 3.5.5.

## 1. Create a reader account in VME

Use a dedicated, read-only account so the dashboard can't change anything and its credential is low-value.

1. In VME, go to **Administration → Roles → + Add → User Role**. Name it `vme-insight reader`.
2. Under **Feature Permissions**, set everything to **None** except:

   | Feature permission | Access | Used for |
   |---|---|---|
   | Admin: Health | Read | Manager health, services, disk |
   | Operations: Alarms | Read | Alarms |
   | Operations: Activity | Read | Recent activity |
   | Infrastructure: Clouds | Read | Clouds |
   | Infrastructure: Clusters | Read | Clusters |
   | Infrastructure: Compute | Read | Hosts and VMs (everything else depends on this) |
   | Infrastructure: Storage | Read | Datastores |
   | Infrastructure: Networks | Read | Networks |
   | Provisioning: Instances: List | Full | Plan and owner columns. This permission has no Read level: **User** lists only the account's own instances, **Full** lists all. It only controls the list; adding, editing and deleting are separate permissions that stay None. |

   HPE describes each permission and its access levels in [Role Permissions](https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/administration/roles/role_permissions.rst).
3. Under **Group Access**, give the role access to all groups (or the groups you want to monitor). Under **Cloud Access**, do the same.
4. Go to **Administration → Users → + Add** ([Users](https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/administration/users/users.rst)). Create `vme-insight`, assign only the role above, and set a strong password.

If a panel stays empty and the collector log shows `HTTP 403` for an endpoint, see [TROUBLESHOOTING](TROUBLESHOOTING.md#http-403) for which permission it needs.

> **API token instead of a password.** You can log in as the reader once and generate a `morph-api` token under **User Settings → API Access** ([User Settings](https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/administration/user_settings/user_settings.rst)), then use `api_token:` instead of username and password. Tokens expire after the client's *access token validity interval*, which an administrator sets under **Administration → Settings → Clients** ([OAuth clients](https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/administration/settings/clients.rst)). The expiry is shown next to the token. With a password, the collector logs in again by itself when its session expires, so it never needs a token renewed.

## 2. Get the code

```bash
git clone https://github.com/grahamfairbank/vme-insight.git
cd vme-insight
```

## 3. Set the passwords for the stack

```bash
cp .env.example .env
chmod 600 .env
```

Edit `.env` and replace every `change-me`. `openssl rand -base64 18` makes a good password. `GRAFANA_PORT` is the port Grafana listens on (default 3000). All settings are in [CONFIGURATION](CONFIGURATION.md#env).

## 4. Point the collector at VME

```bash
cp config/config.example.yaml config/config.yaml
chmod 600 config/config.yaml
```

The file can belong to any user, including root: the collector container reads it once at start, as root, keeps a private copy, then drops to an unprivileged user before running anything.

Set `morpheus.url` (for example `https://vme-manager.example.com`), `username` and `password`.

**TLS.** VME installs a self-signed certificate. Pin it rather than turning verification off:

```bash
docker compose build
docker compose run --rm collector python -m vmeinsight.tlsinfo
```

It prints the manager's certificate and a line ready to paste:

```
# Copy the next line into the morpheus: section of config/config.yaml,
# replacing the empty tls_fingerprint: "" (keep the two leading spaces):
  tls_fingerprint: "0B:6F:87:...:58:6B"
```

Copy that `tls_fingerprint:` line **from the command's output** into `config/config.yaml`, in place of the empty `tls_fingerprint: ""` under `morpheus:`. Keep the indent and the quotes, so it looks like this:

```yaml
morpheus:
  url: https://vme-manager.example.com
  username: "vme-insight"
  password: 'your password'
  tls_fingerprint: "0B:6F:87:...:58:6B"
```

**Optional: check the fingerprint independently.** The command reads the certificate over the network. To rule out anything intercepting that connection, compare the fingerprint with what a machine you trust sees: view the certificate details of `https://<manager>` in a browser, or run this on another host. The two must match exactly:

```bash
echo | openssl s_client -connect vme-manager.example.com:443 2>/dev/null | openssl x509 -noout -fingerprint -sha256
```

The other TLS options are `ca_bundle` (if the manager has a certificate from your own CA) and `insecure: true` (lab only). See [CONFIGURATION](CONFIGURATION.md#tls). If you later replace the self-signed certificate with a CA-signed one ([SSL Certificates](https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/getting_started/additional/morpheusSslCerts.rst)), switch to `ca_bundle` or re-pin.

> Always use `https://`. VME also answers API calls on plain `http://`, which would send the password unencrypted. The collector upgrades `http://` URLs to `https://` unless you set `allow_http: true`.

## 5. Start

```bash
docker compose up -d
docker compose logs -f collector
```

A healthy start looks like this:

```
INFO vmeinsight.db: schema ready (raw 90d, hourly 730d)
INFO vmeinsight.morpheus: authenticated to https://vme-manager.example.com as vme-insight
INFO vmeinsight: inventory: 5 items in 1131 ms
INFO vmeinsight: metrics: 353 items in 1256 ms
INFO vmeinsight: storage: 6 items in 185 ms
INFO vmeinsight: health: 49 items in 285 ms
INFO vmeinsight: lifecycle: 96 items in 894 ms
```

## 6. Verify

1. Open `http://<docker-host>:<GRAFANA_PORT>` and sign in with the admin user from `.env`. The **VME Overview** dashboard is the home page.
2. Check that every panel query runs:

   ```bash
   python3 tools/check_dashboards.py
   ```

   It should report `0 errors`. Exporter panels report `empty` until step 7 is done, and so do panels for things you don't have (no alarms, no collector errors).
3. The **VME Manager & Collector** dashboard shows the last run of each collector task.

## 7. Optional: exporters on the HVM hosts

These add kernel-level host and per-VM metrics, and per-mount filesystem monitoring. See [EXPORTERS](EXPORTERS.md). In short, on the vme-insight host:

```bash
./tools/fetch-exporter-packages.sh
docker compose --profile installer up -d installer
```

Then on each HVM host, as a user with sudo:

```bash
curl -fsSL http://<vme-insight-host>:8097/install-exporters.sh | sudo bash
```

A successful run ends with:

```
== checks
vme-node-exporter              active
prometheus-libvirt-exporter    active
node_* series on :9100:        796
VMs seen by libvirt on :9177:  1
Done. vme-insight will start scraping this host within a minute.
```

Allow TCP 9100 and 9177 from the vme-insight host if a firewall is active. Prometheus finds the hosts by itself.

## Offline installs

Grafana downloads one panel plugin on first start: **Treemap** by Grafana Labs (`marcusolsson-treemap-panel`, pinned to 2.1.1), used by the VM resource-weight panels. Without internet access from the Docker host, either:

* host the plugin zip on an internal web server and point Grafana at it. On a connected machine, download `https://grafana.com/api/plugins/marcusolsson-treemap-panel/versions/2.1.1/download`, then set in `.env`:
  ```bash
  GRAFANA_PLUGINS="https://intranet.example.com/marcusolsson-treemap-panel-2.1.1.zip;marcusolsson-treemap-panel"
  ```
* or set `GRAFANA_PLUGINS=` (empty) to skip it. Everything else works; the three treemap panels show *Panel plugin not found*.

The other images (TimescaleDB, Grafana, Prometheus, Python) need to be in a reachable registry as usual.

## Upgrading

```bash
git pull
docker compose build
docker compose up -d
```

The collector applies schema changes when it starts. Dashboards reload within a minute. If you edited a provisioned dashboard in the Grafana UI, save a copy first (**Save as**), because provisioning overwrites the original.

## Backup and restore

The data lives in Docker volumes: `db-data` (TimescaleDB), `grafana-data` (users, preferences) and `prom-data` (exporter metrics). To back up the database:

```bash
docker compose exec -T timescaledb pg_dump -U vme -Fc vme > vme-insight-$(date +%F).dump
```

To restore into a fresh stack, start only the database, restore, then start the rest:

```bash
docker compose up -d timescaledb
docker compose exec -T timescaledb pg_restore -U vme -d vme --clean --if-exists < vme-insight-YYYY-MM-DD.dump
docker compose up -d
```

## Optional: dashboards inside VME

To show these dashboards on VME's own host, VM, instance and cluster pages, continue with **[VME-PLUGIN](VME-PLUGIN.md)**.

## Reinstalling or starting over

The data lives in Docker volumes named after the project (`vme-insight_db-data` and so on), **not** in the checkout folder. Deleting the folder, cloning again or writing a new `.env` keeps them, together with the passwords they were created with: `DB_PASSWORD` and `GRAFANA_ADMIN_PASSWORD` only take effect when their volume is first created. A reinstall with new passwords then fails with *The database rejected DB_PASSWORD from .env*.

For a truly clean install, remove the volumes before starting. **This deletes all collected data, Grafana users and settings, and Prometheus data:**

```bash
cd ~/vme-insight
docker compose --profile https --profile installer down -v
docker compose up -d
docker compose logs -f collector
```

To keep the data, reuse the old `.env`, or change the passwords inside the running services instead (see [TROUBLESHOOTING](TROUBLESHOOTING.md#collector-wont-start)).

## Removing

```bash
docker compose --profile https --profile installer down      # stop, keep data
docker compose --profile https --profile installer down -v   # stop and delete all data
```

The `--profile` flags make sure the optional https front end and installer are included. For a complete removal (images, exporters on the hosts, certificates on browser machines, the VME account and plugin), follow [Full deinstallation](TROUBLESHOOTING.md#full-deinstallation).
