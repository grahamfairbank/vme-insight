# Security

vme-insight only reads from VME. It holds a credential for your virtualization manager, so treat the deployment accordingly.

## Credentials

* Use a **dedicated read-only VME account** ([INSTALL](INSTALL.md#1-create-a-reader-account-in-vme), [Role Permissions](https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/administration/roles/role_permissions.rst)). Never use an admin account in production. If the collector host is compromised, a read-only credential exposes inventory, not control.
* `config/config.yaml` and `.env` hold secrets. Keep them `chmod 600`. They are git-ignored; keep them that way.
* All `morpheus.*` settings can come from environment variables instead (`VME_PASSWORD`, etc.) if you'd rather inject them from a secrets manager.
* The collector container starts as root only to copy the mounted config into a private, mode-600 copy, then runs as uid 1000 with no Linux capabilities and no-new-privileges (`collector/entrypoint.sh`).
* The database has two users: `vme` (owner, used by the collector) and `grafana_ro` (SELECT only, used by Grafana). Grafana can't modify data.

## Transport

* `http://` URLs are upgraded to `https://`. VME answers API calls on plain HTTP, which would expose the password on the network.
* For VME's self-signed certificate, **pin it** with `tls_fingerprint` rather than disabling verification. `insecure: true` exists for labs only and logs a warning at every start.

## Network exposure

| Port | Service | Exposed by default | Notes |
|---|---|---|---|
| `GRAFANA_PORT` (3000) | Grafana | Yes, unless `GRAFANA_BIND=127.0.0.1` | Put a reverse proxy with TLS in front if it's reachable beyond a trusted network (the optional https front end does this). Change the admin password. Sign-up is disabled. |
| `HTTPS_PORT` (3443) | https front end | Only with `--profile https` | TLS, and only the `HTTPS_ALLOW` networks get through. See [CONFIGURATION](CONFIGURATION.md#https-front-end). |
| 5432 | TimescaleDB | No | Internal to the compose network. A commented `127.0.0.1` mapping is available for admin access. |
| 9090 | Prometheus | No | Internal. A commented `127.0.0.1` mapping is available. |
| 9100, 9177 on HVM hosts | Exporters | Only if you install them | No authentication. Bind to the management IP and firewall to the vme-insight host. |

## Certificates for the https front end

Browsers that show the plugin tabs must trust the front end's certificate. Adding trust is the riskiest step in the whole setup, so the options are ordered from least to most new trust in [VME-PLUGIN](VME-PLUGIN.md#3-make-browsers-trust-the-certificate):

1. A certificate from your organization's CA, or a public one: nothing new to trust.
2. `tools/make-cert.sh host`: a self-signed certificate for this host only (`CA:FALSE`), so it can't vouch for any other site.
3. `tools/make-cert.sh ca`: your own CA, restricted by name constraints to your domain and network, with its key kept off the host.
4. The built-in CA (`HTTPS_TLS=internal`): it can sign for **any** site and its key lives in a Docker volume. Lab use only.

Whichever you use, check the SHA-256 fingerprint before importing, import for your own account rather than machine-wide where you can, and remove the trust when it's no longer needed. vme-insight never ships a certificate or key.

## Grafana users

Anyone with Grafana **Editor** or **Admin** rights can run arbitrary read queries against the database through Explore. The database contains the full API objects (`raw` columns), including host names, IPs and user names, but **no VME credentials**. Give Editor rights only to people who could already see this in VME.

## Anonymous viewers

`GRAFANA_ANONYMOUS=true` lets anyone who reaches Grafana view every dashboard as a read-only **Viewer**, without signing in. The VME UI plugin needs it, because a sign-in inside a frame on another site doesn't stick. Enable it only with:

* `GRAFANA_BIND=127.0.0.1`, so Grafana's own port isn't reachable from other machines, and
* the https front end with `HTTPS_ALLOW` set to the networks your VME admins use.

What an anonymous Viewer can do: open every dashboard and change its time range and variables; download CSV exports; list data sources (names and types, no passwords); send read queries to the data sources through Grafana's API, as the `SELECT`-only `grafana_ro` user. It can't edit dashboards, use Explore, or see users and settings. There is no per-person identity: everyone on the allowed networks sees the same data. Admins still sign in (top right) for anything else.

## What's stored

The `raw` JSON columns keep the API objects as returned, **minus secrets**. VME includes some sensitive fields in its API responses, for example every server's agent `apiKey` and each cloud's `credential` block. Before storing anything, the collector replaces any field whose name looks like a password, secret, token, API key, credential, private key or hash with `<redacted>`. The `probe` tool applies the same redaction.

What remains (host names, IPs, user names, configuration) is still worth protecting. Restrict database and Grafana Editor access as above.

## Reporting a vulnerability

Please open a private security advisory on the repository rather than a public issue.
