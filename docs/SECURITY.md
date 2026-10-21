# Security

vme-insight only reads from VME. It holds a credential for your virtualization manager, so treat the deployment accordingly.

## Credentials

* Use a **dedicated read-only VME account** ([INSTALL](INSTALL.md#1-create-a-reader-account-in-vme), [Role Permissions](https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/administration/roles/role_permissions.rst)). Never use an admin account in production. If the collector host is compromised, a read-only credential exposes inventory, not control.
* `config/config.yaml` and `.env` hold secrets. Keep them `chmod 600`. They are git-ignored; keep them that way.
* All `morpheus.*` settings can come from environment variables instead (`VME_PASSWORD`, etc.) if you'd rather inject them from a secrets manager.
* The database has two users: `vme` (owner, used by the collector) and `grafana_ro` (SELECT only, used by Grafana). Grafana can't modify data.

## Transport

* `http://` URLs are upgraded to `https://`. VME answers API calls on plain HTTP, which would expose the password on the network.
* For VME's self-signed certificate, **pin it** with `tls_fingerprint` rather than disabling verification. `insecure: true` exists for labs only and logs a warning at every start.

## Network exposure

| Port | Service | Exposed by default | Notes |
|---|---|---|---|
| `GRAFANA_PORT` (3000) | Grafana | Yes | Put a reverse proxy with TLS in front if it's reachable beyond a trusted network. Change the admin password. Sign-up is disabled. |
| 5432 | TimescaleDB | No | Internal to the compose network. A commented `127.0.0.1` mapping is available for admin access. |
| 9090 | Prometheus | No | Internal. A commented `127.0.0.1` mapping is available. |
| 9100, 9177 on HVM hosts | Exporters | Only if you install them | No authentication. Bind to the management IP and firewall to the vme-insight host. |

## Grafana users

Anyone with Grafana **Editor** or **Admin** rights can run arbitrary read queries against the database through Explore. The database contains the full API objects (`raw` columns), including host names, IPs and user names, but **no VME credentials**. Give Editor rights only to people who could already see this in VME.

## What's stored

The `raw` JSON columns keep the API objects as returned, **minus secrets**. VME includes some sensitive fields in its API responses, for example every server's agent `apiKey` and each cloud's `credential` block. Before storing anything, the collector replaces any field whose name looks like a password, secret, token, API key, credential, private key or hash with `<redacted>`. The `probe` tool applies the same redaction.

What remains (host names, IPs, user names, configuration) is still worth protecting. Restrict database and Grafana Editor access as above.

## Reporting a vulnerability

Please open a private security advisory on the repository rather than a public issue.
