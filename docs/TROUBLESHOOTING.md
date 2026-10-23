# Troubleshooting

Start with the collector log and the **VME Manager & Collector** dashboard:

```bash
docker compose ps
docker compose logs --tail 50 collector
```

## Docker commands fail

| Log message | Cause | Fix |
|---|---|---|
| `permission denied while trying to connect to the docker API at unix:///var/run/docker.sock` | Your account isn't allowed to use Docker. Installing Docker doesn't add any user to the `docker` group, so this is normal on a fresh install. | **apt (`docker.io` or `docker-ce`):** `sudo usermod -aG docker $USER`, then log out and back in (or `newgrp docker`) and check with `docker ps`. **Snap** (`snap list docker` shows it): `sudo addgroup --system docker && sudo adduser $USER docker && sudo snap disable docker && sudo snap enable docker`, then log out and back in. Or prefix the commands with `sudo`; the `tools/` scripts that call Docker then need `sudo` too. Membership of the `docker` group is equivalent to root on that machine. |
| Volumes or `./config` not found, only with the Docker snap | The snap can only reach files under your home directory | Keep the vme-insight checkout under `$HOME` |

## Collector won't start

| Log message | Cause | Fix |
|---|---|---|
| `config: morpheus.url is not set` | No `config/config.yaml`, or `url` empty | Copy `config.example.yaml` and fill it in |
| `morpheus: set api_token, or username and password` | Credentials missing | Set them in `config.yaml` |
| `PermissionError ... /config/config.yaml` (versions before 0.4.1) | The collector ran as uid 1000 and couldn't read a config owned by another user (e.g. root) with mode 600 | Upgrade to 0.4.1 or later (`git pull && docker compose build && docker compose up -d`). Since 0.4.1 the config can have any owner and mode: the container copies it privately before dropping privileges. Workaround on older versions: `chown 1000 config/config.yaml`. |
| `waiting for database` repeating | TimescaleDB not ready | `docker compose logs timescaledb` |

## Connecting to VME

| Symptom | Cause | Fix |
|---|---|---|
| `Fingerprints did not match` | The manager's certificate changed (renewed or replaced) | Check the new certificate is genuine, then run `tlsinfo` again and update `tls_fingerprint` |
| `CERTIFICATE_VERIFY_FAILED` | Self-signed certificate and no TLS option set | Set `tls_fingerprint` (see [CONFIGURATION](CONFIGURATION.md#tls)) |
| `hostname mismatch` | With `ca_bundle`, the hostname in `url` isn't on the certificate | Use a name on the certificate, or `tls_fingerprint` |
| `switching to https://` warning | `url` starts with `http://` | Intended. Change `url` to `https://` to silence it. |
| `HTTP 401 on /oauth/token` | Wrong username or password, or the account is locked | Log in to the VME UI with the same account to check |
| `HTTP 401` on other endpoints, repeating | API token expired | Create a new token, or use username/password |
| Connection timed out / refused | Network or firewall | From the Docker host: `curl -k https://<manager>/api/ping` should return `{"success":true,...}` |

## HTTP 403

The reader role lacks a permission. The collector skips 403 endpoints (log them with `log_level: DEBUG`) and the matching panels stay empty:

| Empty panels | Endpoint | Role feature permission |
|---|---|---|
| Hosts, VMs, everything | `/api/servers` | Infrastructure: Compute → Read |
| Clusters | `/api/clusters` | Infrastructure: Clusters → Read |
| Datastores | `/api/data-stores` | Infrastructure: Storage → Read |
| Manager panels, services | `/api/health` | Admin: Health → Read |
| Alarms | `/api/health/alarms` | Operations: Alarms → Read |
| Recent activity | `/api/activity` | Operations: Activity → Read |
| Clouds | `/api/zones` | Infrastructure: Clouds → Read |
| Networks | `/api/networks` | Infrastructure: Networks → Read |
| Plan, owner columns | `/api/instances` | Provisioning: Instances: List → Full |

Permission names and levels: [Role Permissions](https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/administration/roles/role_permissions.rst).

The role also needs access to the groups and clouds to be monitored. Missing group access shows as missing servers rather than errors.

## Dashboards

| Symptom | Cause | Fix |
|---|---|---|
| Every panel shows an error about `grafana_ro` | The collector hasn't created Grafana's database user yet, or `GRAFANA_DB_PASSWORD` changed | Start the collector. After changing the password: `docker compose up -d --force-recreate collector grafana` |
| Panels empty for the first minutes | No data yet | Wait two collection cycles |
| VM memory % or OS empty | No guest agent in the VM | Install and start `qemu-guest-agent` in the guest |
| Exporter dashboards empty | Exporters not installed, or ports blocked | See [EXPORTERS](EXPORTERS.md#check) |
| Edits to a dashboard disappear | Provisioned dashboards are reloaded from disk | **Save as** a copy, or change `tools/build_dashboards.py` |
| Host counted as a VM, or the reverse | Unusual server type code | `classification` in [CONFIGURATION](CONFIGURATION.md#classification) |

`python3 tools/check_dashboards.py` runs every panel query and prints any SQL or PromQL errors.

## https front end

| Symptom | Cause | Fix |
|---|---|---|
| `ERR_SSL_PROTOCOL_ERROR` / "sent an invalid response" when opening `https://<ip>:3443` | Browsing by IP: the browser sends no server name and the front end has no certificate to offer | Add the IP to `HTTPS_HOSTNAME`, set `HTTPS_DEFAULT_SNI=<ip>`, make sure the certificate covers the IP, then `docker compose --profile https up -d https`. Or browse by name. |
| `ERR_CERT_AUTHORITY_INVALID` / blank VME tabs | The browser doesn't trust the certificate | [Make browsers trust the certificate](VME-PLUGIN.md#3-make-browsers-trust-the-certificate) |
| `ERR_CERT_COMMON_NAME_INVALID` | The address typed isn't in the certificate | Reissue it with every name and IP users type |
| `403 Forbidden` | The client's network isn't in `HTTPS_ALLOW` | Add its network (CIDR); over a VPN that's the VPN's address range |

## Exporter installer

| Output on the host | Cause | Fix |
|---|---|---|
| `could not download ... from http://...:8097/dist or GitHub` | Packages not fetched on the vme-insight host, and the host has no internet | Run `./tools/fetch-exporter-packages.sh` on the vme-insight host |
| `checksum mismatch` | The file isn't the pinned release | Don't install. Re-run `fetch-exporter-packages.sh` and check where the file came from. |
| `could not work out the management IP` | No route to the vme-insight server | Add `-s -- --listen <ip>` after `bash` |
| `node_* series ... 0` | Service failed to start | `journalctl -u vme-node-exporter -u prometheus-libvirt-exporter -n 50` |
| `ufw is active` | The host firewall is on | Add only the rule your site approves for TCP 9100/9177 from the vme-insight host. **Don't disable UFW**: HPE warns that changing firewall state on HVM hosts can affect cluster quorum and storage ([Host Firewall Ownership](https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/getting_started/installation/hvm_host_prep.rst)). |
| apt `W:` / `NO_PUBKEY` warnings | Seen with older installers that ran `apt-get update`; they point to the host's HPE repository key, not to vme-insight | The current installer doesn't use apt. Raise the key warning with HPE if it appears in normal host updates. |

## Looking at what the API returns

```bash
docker compose run --rm collector python -m vmeinsight.probe
```

This writes a sample of each endpoint the collector uses to `./probe/*.json`. Useful after a VME upgrade, or to attach to an issue. **Review the files before sharing them**: they contain hostnames, IPs and user names.

## Version

The collector logs `VME x.y is older than the supported 9.1` if the manager is older. Older releases may work, but field names differ and some panels may be empty.
