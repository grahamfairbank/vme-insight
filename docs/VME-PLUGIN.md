# Optional: vme-insight inside VME (VME UI plugin)

vme-insight is a complete web site on its own. If you also want its dashboards **inside the VME UI**, install the companion plugin, [vme-insight-plugin](https://github.com/grahamfairbank/vme-insight-plugin). It adds a **vme-insight** tab to every host, VM, instance and cluster page, showing the matching vme-insight dashboard. It can also add a vme-insight dashboard to VME's home page.

This page is the whole setup, end to end. The plugin's own repository has the reference detail: every setting, the authentication options compared, troubleshooting and development.

> The plugin is part of the same community project and carries the same [disclaimer](../README.md#disclaimer): it is not affiliated with, endorsed or supported by HPE or Morpheus Data. Like any plugin, it runs inside your VME manager; check your HPE support terms before installing third-party plugins on a production manager.

## How it fits together

```
 Your browser ── VME page (https://vme-manager) ── vme-insight tab ──┐
                                                                      │ frame, loaded by the browser
                                                                      ▼
                                   vme-insight https front end (:3443, allowlisted networks)
                                                                      │
                                                                      ▼
                                   vme-insight Grafana (anonymous, read-only Viewer)
```

* The plugin only builds a link. The **browser** loads the dashboard straight from vme-insight's Grafana, inside the tab. VME never connects to Grafana, and the plugin stores no credentials.
* The browser must reach Grafana **over https** (VME is https, and browsers block http frames inside https pages), **without a sign-in** (a sign-in inside a frame on another site doesn't stick), and **trust its certificate** (a frame can't show a certificate warning; it just stays blank).
* So this setup turns on vme-insight's https front end and read-only anonymous access, limited to the networks your VME admins use. [SECURITY](SECURITY.md#anonymous-viewers) explains what anonymous viewers can and can't do.

## Compatibility

| vme-insight-plugin | Needs vme-insight | VME |
|---|---|---|
| 0.1.2 and later | 0.2.0 or later (https front end, anonymous access, `vme-widget` dashboard) | 9.1 or later (Plugin API 1.5.0) |
| 0.1.0 – 0.1.1 | 0.2.0 or later | 9.1 or later |

vme-insight works without the plugin. The plugin does nothing without vme-insight. Install them in that order, and upgrade vme-insight first when a plugin release asks for a newer version.

## 1. Before you start

* vme-insight installed and collecting from **the same VME manager** you'll install the plugin on ([INSTALL](INSTALL.md)). The tabs pass VME's ids to the dashboards, so both must describe the same estate.
* The name your users will type for vme-insight, for example `vme-insight.example.com`, resolving to the Docker host.
* The networks your VME admins work from, for example `10.20.0.0/16`.
* A VME account that can manage plugins (**Administration → Integrations**).

## 2. Turn on https and anonymous viewing

Add to `.env`:

```bash
GRAFANA_BIND=127.0.0.1                       # Grafana's own port only on the Docker host
GRAFANA_ALLOW_EMBEDDING=true                 # allow Grafana inside VME pages
GRAFANA_ANONYMOUS=true                       # read-only Viewer without signing in
GRAFANA_ROOT_URL=https://vme-insight.example.com:3443/
GRAFANA_COOKIE_SECURE=true
HTTPS_HOSTNAME=vme-insight.example.com       # the name users type
HTTPS_ALLOW="10.20.0.0/16 192.168.13.0/24"   # networks allowed in; everyone else gets 403
HTTPS_TLS=internal                           # or "/certs/<cert>.pem /certs/<key>.pem", files in https/certs/
```

Then:

```bash
docker compose up -d grafana
docker compose --profile https up -d https
```

vme-insight is now at `https://vme-insight.example.com:3443` for the allowed networks, and `http://<docker-host>:<GRAFANA_PORT>` only answers on the Docker host itself. Admins still sign in (top right → **Sign in**) for anything beyond viewing. Every setting is described in [CONFIGURATION](CONFIGURATION.md#env).

## 3. Make browsers trust the certificate

Skip this if `HTTPS_TLS` points at a certificate your users' machines already trust.

With `HTTPS_TLS=internal`, the front end issues its own certificate from a private root. Export the root once:

```bash
docker compose --profile https cp https:/data/caddy/pki/authorities/local/root.crt vme-insight-root.crt
```

Then, on **each machine whose browser will show the vme-insight tabs**, import `vme-insight-root.crt` as a trusted root:

* **Windows** (Edge, Chrome): use PowerShell, in the folder holding `vme-insight-root.crt`. Pick one option. Don't double-click the certificate to install it: Windows' import wizard files it under *Intermediate Certification Authorities*, where browsers still reject it.

  **Option 1: every user on the machine (needs administrator rights).** Writing to the machine-wide store needs an elevated PowerShell; in a normal window, `Import-Certificate` fails with *Access is denied*. This command opens an elevated window and runs the import there. Approve the **UAC** prompt (*Do you want to allow this app to make changes to your device?* → **Yes**):
  ```powershell
  Start-Process powershell -Verb RunAs -ArgumentList '-NoExit','-Command',"Import-Certificate -FilePath '$PWD\vme-insight-root.crt' -CertStoreLocation Cert:\LocalMachine\Root"
  ```

  **Option 2: just your Windows account (no administrator rights needed).** Edge and Chrome trust this store too. Windows shows a security warning asking you to confirm installing a root certificate; click **Yes**:
  ```powershell
  Import-Certificate -FilePath .\vme-insight-root.crt -CertStoreLocation Cert:\CurrentUser\Root
  ```

  **Check** that it landed in a Root store. It should list *Caddy Local Authority - &lt;year&gt; ECC Root*, under `LocalMachine\Root` (option 1) or `CurrentUser\Root` (option 2):
  ```powershell
  Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root | Where-Object Subject -like '*Caddy Local Authority*' | Format-List PSParentPath, Subject, Thumbprint, NotAfter
  ```

  **Clean up** a copy left by an earlier double-click install, which Windows filed as an intermediate. Removing it from `LocalMachine\CA` needs the elevated window from option 1; `CurrentUser\CA` works in any window:
  ```powershell
  Get-ChildItem Cert:\LocalMachine\CA, Cert:\CurrentUser\CA | Where-Object Subject -like '*Caddy Local Authority*' | Remove-Item
  ```

  Then close every browser window and reopen it.
* **macOS**: Keychain Access → System, import, then set it to **Always Trust**.
* **Firefox** keeps its own list: Settings → Privacy & Security → Certificates → View Certificates → Authorities → Import.

A frame can't show a certificate warning, so an untrusted certificate leaves embedded dashboards blank. With your own certificate, put the files in `https/certs/` and set `HTTPS_TLS`.

## 4. Check from your workstation

Open `https://vme-insight.example.com:3443/d/vme-overview` in a new browser tab. VME Overview should appear **without a certificate warning and without a sign-in page**.

| You see | Fix |
|---|---|
| Certificate warning | The root isn't trusted on this machine yet: step 3. |
| `Forbidden` | This machine's network isn't in `HTTPS_ALLOW`. |
| Grafana's sign-in page | `GRAFANA_ANONYMOUS=true` missing, or Grafana not restarted. |
| Nothing loads | Name resolution or a firewall between you and the Docker host. |

## 5. Install the plugin

1. Download `vme-insight-plugin-<version>.jar` from the plugin's [releases](https://github.com/grahamfairbank/vme-insight-plugin/releases), or build it from source ([plugin INSTALL](https://github.com/grahamfairbank/vme-insight-plugin/blob/main/docs/INSTALL.md)).
2. In VME, go to **Administration → Integrations → Plugins** and click **Add**. Upload the jar. It appears as **vme-insight**, status **loaded** ([HPE: Plugins](https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/administration/integrations/plugins.rst)).
3. Click the pencil icon on the **vme-insight** row. Set **vme-insight Grafana URL** to `https://vme-insight.example.com:3443`, and save. Leave the other settings at their defaults; they're described in the plugin's [CONFIGURATION](https://github.com/grahamfairbank/vme-insight-plugin/blob/main/docs/CONFIGURATION.md).

## 6. Check in VME

Reload VME, then open:

* a cluster under **Infrastructure → Clusters**: the **vme-insight** tab shows VME Overview for that cluster;
* a host under **Infrastructure → Compute → Hosts**: VME Hosts for that host. Hosts have many tabs, so look in the **▼** menu at the end of the tab row;
* a VM under **Infrastructure → Compute → Virtual Machines**, or an instance under **Provisioning → Instances**: VME Virtual Machines for it.

**Open in vme-insight ↗** at the top of each tab opens the dashboard full size. If a tab is blank, says the content is blocked, or shows "might be having issues", see the plugin's [TROUBLESHOOTING](https://github.com/grahamfairbank/vme-insight-plugin/blob/main/docs/TROUBLESHOOTING.md).

## 7. Optional extras

* **vme-insight on VME's home page.** **Administration → Settings → Appliance → Dashboards to Display**: add **vme-insight** (VME lists it as *Vme-insight*). It shows a row of tiles from vme-insight's **VME Summary tiles** dashboard (`vme-widget`): clusters, hosts, VMs, VMs running, active alarms, VME manager version, worst VM CPU ready, and VMs over 10% ready. This changes the home page for every user.
* **Only some VME roles see the tabs.** Tick **Only show to roles with the vme-insight permission** in the plugin settings, then grant **vme-insight: View dashboards → Read** to those roles under **Administration → Roles**. This hides the tabs in VME; it doesn't protect Grafana, which the network allowlist does.
* **A link on every VME page.** Tick **Show a vme-insight link on every page**.

## Removing

1. In VME, delete the plugin on **Administration → Integrations → Plugins** (trash icon). If you added it to **Dashboards to Display**, check that list.
2. In vme-insight, stop the front end with `docker compose --profile https stop https`, set `GRAFANA_ANONYMOUS=false` (and `GRAFANA_BIND=0.0.0.0` if you want the plain port back on the network), and `docker compose up -d grafana`.
3. Optionally remove the root certificate from client machines. On Windows (elevated PowerShell for `LocalMachine`):
   ```powershell
   Get-ChildItem Cert:\LocalMachine\Root, Cert:\CurrentUser\Root | Where-Object Subject -like '*Caddy Local Authority*' | Remove-Item
   ```
