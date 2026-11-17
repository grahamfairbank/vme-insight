# vme-insight virtual appliance

A ready-to-run virtual machine image of vme-insight for HPE Morpheus VM Essentials. Import it as a virtual image, provision a VM from it on an HVM (HPE Virtual Machine) cluster, give it the Morpheus URL and a read-only account, and the dashboards start. Nothing else to install: Docker, vme-insight and every container image it needs are inside, so it works without internet access.

* **Image:** `vme-insight-appliance-<version>.qcow2` (QCOW2, compressed), with `SHA256SUMS`.
* **Inside:** Debian GNU/Linux 13 cloud image, Docker and Docker Compose from Debian, the QEMU guest agent, cloud-init, vme-insight in `/opt/vme-insight`, and its container images (TimescaleDB, Grafana with the treemap panel, Prometheus, Caddy, the collector).
* **No accounts or passwords in the image.** You sign in with the SSH key or user Morpheus injects through cloud-init. The database and Grafana passwords are generated on each VM at first boot.

**Why Debian.** Everything in Debian's main archive is free software that anyone may redistribute, modified or not, so a complete image with the operating system inside can be published for download with no license, subscription or permission needed. Some other distributions need a paid subscription for each system, or their publisher's permission to redistribute a modified image.

> **Community project.** Not affiliated with, endorsed, sponsored or supported by Hewlett Packard Enterprise, Morpheus Data, or the Debian Project. Third-party licenses: `/usr/share/doc/vme-insight-appliance/NOTICE` in the VM.

## You own the appliance

Once it's provisioned, the VM is yours to run like any other Linux server you manage. Nobody else patches, backs up or watches it:

* **Debian updates** (security fixes, the kernel, Docker): your usual method. See [Keeping it up to date](#keeping-it-up-to-date).
* **vme-insight updates:** run `sudo vme-insight-update` when the login message says a new release is out.
* **Backups:** VM snapshots or backups in Morpheus, or vme-insight's own [backup and restore](INSTALL.md#backup-and-restore).
* **Access:** who can SSH in, who can reach port 3000 and the https port, and the [passwords](#changing-passwords).
* **Disk space:** the database grows with the number of hosts and VMs (see [Sizing](#sizing)).
* **The Morpheus account:** if its token expires or its password changes, run `sudo vme-insight-setup` again.

vme-insight is a community project with no support contract. Report problems at https://github.com/grahamfairbank/vme-insight/issues.

## Requirements

What the appliance needs from Morpheus and the network, and what it doesn't:

| | Needed? | Details |
|---|---|---|
| **Cloud-init user in Morpheus** | **Yes, to sign in** | Set this up before you provision. Go to **Administration → Settings → Provisioning → Cloud-Init Settings** and enter a username, plus a password, an SSH key pair, or both. Morpheus creates that user in the VM through cloud-init. The image has no password or default login of its own, so without this you can't sign in to the VM at all. (The dashboards still start if the settings arrive through user data, but you can't run `vme-insight-setup`, update or troubleshoot.) |
| **Storage** | Any datastore | The VM sees an ordinary virtio disk, wherever the HVM cluster keeps it: a GFS2 datastore on external block storage (tested), local storage or anything else. The appliance needs **no NFS**. It doesn't mount shared storage, and all its data (database, Grafana) is on its own disk. The NFS client isn't installed. |
| **Network address** | **DHCP, an IP pool or a static address** | The VM gets its address one of three ways, all set on the Morpheus network: a DHCP server on that network; an **IP pool** assigned to the network, from which Morpheus picks an address; or a static address you type in when provisioning (the network needs **Allow IP Override**). Cloud-init applies whatever Morpheus passes to it. With none of these, the VM comes up with no address and nothing can reach it. Tested with DHCP and with a typed static address; IP pools weren't tested, but Morpheus passes the address to cloud-init the same way. |
| **DNS** | If the Morpheus URL is a name | With DHCP, the DNS servers come from DHCP. With a static address they come from the Morpheus network (or IP pool) settings, and if those have none, Morpheus uses **8.8.8.8**, which a closed network can't reach. Set DNS on the network first, or set `dns_servers` on the appliance (see [DNS servers](#dns-servers)). With `url: https://<ip>` the appliance needs no DNS for its core job. |
| **Time (NTP)** | Yes | Accurate time matters for the charts and for TLS. By default the VM sets its clock from Debian's public time servers on the internet. Without internet access, give it your own (see [Your own time servers](#your-own-time-servers)). |
| **To Morpheus** | Yes | HTTPS (443) from the appliance to the Morpheus appliance, with a read-only account. |
| **Morpheus Appliance URL** | Reachable from the HVM hosts | Not specific to vme-insight: to provision from a new image, each HVM host downloads it from Morpheus's Appliance URL (Administration → Settings → Appliance). See Troubleshooting if provisioning fails with "Image is not in qcow2 format". |
| **From users** | Yes | TCP 3000 (Grafana) or the https port (443 or 3443, see [The https port](#the-https-port)) from the browsers of the people who view the dashboards, including inside the Morpheus UI. Optionally SSH (22) for administration. |
| **To HVM hosts** | Only with the exporters | TCP 9100 and 9177 to each HVM host, if you install the optional [exporters](EXPORTERS.md). |
| **Internet** | No | Only for a few optional extras. See [Internet access](#internet-access). |
| **Morpheus agent** | No | Choose either way when importing. vme-insight reads everything through the Morpheus API. |

### Internet access

The appliance doesn't need the internet. Docker, vme-insight, every container image and the Grafana plugin are already inside, so it starts and collects data on a closed network. It goes out only for these optional things:

| Destination | What for | When | Without it |
|---|---|---|---|
| `endoflife.date` (HTTPS) | End-of-life dates for guest operating systems, on the Lifecycle dashboard | Once a day | Those dates are blank; everything else works |
| `api.github.com` (HTTPS) | The "update available" notice at login | Once a day (turn off with `updates: {check: false}`) | No notice |
| `github.com`, `codeload.github.com`, `grafana.com`, Docker Hub, PyPI (HTTPS) | `sudo vme-insight-update`: the new release, the Grafana plugin, container images, the collector's Python packages | Only when you run it | Update by provisioning a VM from the new image instead (see [Keeping it up to date](#keeping-it-up-to-date)) |
| `deb.debian.org`, `security.debian.org` (HTTPS/HTTP) | Debian updates | When you (or your tooling) run apt | Use your own Debian mirror |
| `*.debian.pool.ntp.org` (UDP 123) | Time | All the time | Use [your own time servers](#your-own-time-servers) |

All of these can go through an HTTP(S) proxy (see [Proxy](#proxy)), except NTP.

### Your own time servers

The VM keeps its clock right with `systemd-timesyncd`, Debian's built-in time client. Out of the box it uses time servers from DHCP if your network hands them out, otherwise Debian's public servers on the internet (`0.debian.pool.ntp.org` to `3.debian.pool.ntp.org`, UDP port 123). If the VM can't reach them, or your organization runs its own time servers, set `time_servers` to yours: names or IP addresses, separated by spaces.

* **At provisioning:** add it to the settings in the Cloud-Init User Data from [step 3](#3-provision-a-vm-and-pass-the-settings):

  ```yaml
  time_servers: ntp1.example.com ntp2.example.com
  ```

* **On a running VM:** run `sudo vme-insight-setup` and answer the time servers question (step 6). Or edit `/etc/vme-insight/appliance.yaml` and run `sudo vme-insight-apply`.

The appliance writes `/etc/systemd/timesyncd.conf.d/vme-insight.conf` and restarts the time client. Setting it back to empty returns to the default. (Before 0.7.0 this was a few shell commands writing `local.conf` in the same folder. That file still works, but `time_servers` takes priority over it.)

**Check it:** `timedatectl timesync-status` shows which server the VM uses (the `Server:` line), and `timedatectl` should say `System clock synchronized: yes` within a minute.

### DNS servers

The VM gets its DNS servers the same way as its address (see [Requirements](#requirements)):

* **With DHCP**, from the DHCP server.
* **With an IP pool or a static address**, from the Morpheus network or IP pool settings. If those have none, Morpheus uses **8.8.8.8**.

It's best to set DNS correctly where it comes from, because every VM provisioned later gets it too. To use other DNS servers on this VM, set `dns_servers` to their IP addresses, separated by spaces:

* **At provisioning:** add it to the settings in the Cloud-Init User Data from [step 3](#3-provision-a-vm-and-pass-the-settings):

  ```yaml
  dns_servers: 10.0.0.53 10.0.0.54
  dns_search: example.com        # optional: domains to try for short names
  ```

* **On a running VM:** run `sudo vme-insight-setup` and answer the DNS questions (step 6). It shows the servers in use now. Or edit `/etc/vme-insight/appliance.yaml` and run `sudo vme-insight-apply`.

Your servers **replace** the ones from Morpheus or DHCP (they aren't added to them), and the containers restart to use them. Setting `dns_servers` back to empty (`-` in the wizard) returns to the servers from Morpheus or DHCP. DNS servers are given by IP address, because a name would need DNS to find them.

The appliance leaves cloud-init's network file (`/etc/netplan/50-cloud-init.yaml`) as it is. It adds a small systemd-networkd file for each network, `/etc/systemd/network/10-netplan-<interface>.network.d/vme-insight-dns.conf`, which clears the old servers and sets yours. Don't edit `/etc/resolv.conf`: the system rewrites it.

**Check it:** `resolvectl dns` lists the servers for each network interface, and `resolvectl query morpheus.example.com` (your Morpheus name) shows that a name resolves.

### Proxy

If the appliance reaches the internet through an HTTP(S) proxy, set it in either of two ways:

* **At provisioning:** put it in the [user data](#3-provision-a-vm-and-pass-the-settings):

  ```yaml
  proxy:
    url: http://proxy.example.com:3128
    no_proxy: .example.com 10.0.0.0/8     # optional: more hosts, domains or networks to reach directly
  ```

* **On a running VM:** run `sudo vme-insight-setup` and enter the proxy URL and any hosts to reach directly when asked (question 5). Press Enter at the other questions to keep their current values. Or edit the `proxy:` section of `/etc/vme-insight/appliance.yaml` as above and run `sudo vme-insight-apply`.

To change the proxy later, do the same again. To take it out, run `sudo vme-insight-setup` and enter `-` for the proxy. When the proxy changes, the appliance restarts Docker, so the dashboards are unavailable for a minute.

**Check it:** `sudo vme-insight-update --check` contacts GitHub through the proxy and says which release is the latest. `sudo cat /etc/vme-insight/proxy.env` shows the proxy and the addresses reached directly.

`vme-insight-apply` points everything that goes to the internet at the proxy:

| What | How |
|---|---|
| The collector (end-of-life dates from endoflife.date) | `HTTP_PROXY`/`HTTPS_PROXY`/`NO_PROXY` in the containers, through Docker's client settings (`/root/.docker/config.json`) |
| `vme-insight-update` (GitHub, grafana.com) and the daily update check | `/etc/vme-insight/proxy.env` |
| Container image pulls and the collector build (Docker Hub, PyPI) | A Docker service drop-in (`/etc/systemd/system/docker.service.d/vme-insight-proxy.conf`) and the client settings above |
| apt, for your Debian updates | `/etc/apt/apt.conf.d/80vme-insight-proxy` |

The connection to Morpheus never uses the proxy: the appliance adds the Morpheus host to `no_proxy` itself, because certificate pinning (`tls_fingerprint`) needs a direct connection. The containers' traffic to each other is direct too.

* A password in the URL (`http://user:password@proxy:3128`) works. It is stored in those files readable by root only, like the Morpheus token.
* NTP doesn't go through an HTTP proxy. Behind one, use your own time servers (above).
* The appliance doesn't read Morpheus's own proxy settings (Administration → Settings → Provisioning). Put the proxy in `appliance.yaml`.
* A proxy that inspects TLS with its own certificate authority: let the appliance's destinations bypass inspection. Otherwise apt and `vme-insight-update` need that CA added to the VM (`/usr/local/share/ca-certificates/`, then `sudo update-ca-certificates`), and the collector, which uses its own CA bundle, can't fetch end-of-life dates. Everything else keeps working.

## Sizing

Size the VM generously when you provision it. Growing the disk later is easy, but more memory isn't fully used by the database (see [Changing the size later](#changing-the-size-later)).

| | Minimum | Recommended |
|---|---|---|
| vCPU | 2 | 4 |
| Memory | 4 GB | 4 GB up to about 300 VMs; 8 GB for more, or for many people viewing at once |
| Disk | 20 GB | From the formula below, rounded up |

### Memory

4 GB is the minimum, and it runs well from 4 GB up:

* In normal running, the containers use about 0.5 GB (measured in the test lab: TimescaleDB 290 MB, Grafana 95 MB, Prometheus 70 MB, collector 30 MB, Caddy 15 MB), and Debian and Docker about 0.3 GB more.
* The peaks are much higher: the first boot unpacks and loads about 4 GB of container images, `vme-insight-update` pulls new images and builds the collector, and dashboards over 90 days of data make the database work hard.
* TimescaleDB tunes itself for a quarter of the VM's memory (at least 1 GB). From 0.7.0 it tunes again at boot when the VM's memory changes. To give it a fixed amount instead, set `database: {memory: 4GB}` (or answer the database question in `sudo vme-insight-setup`).

The database's memory use doesn't grow much with the number of VMs; the number of people viewing dashboards at the same time matters more. 8 GB is a sensible choice above about 300 VMs, but estates that large haven't been tested.

### Disk

The disk holds Debian, Docker and the container images (about 7 GB after first boot), room for `vme-insight-update` to download new images next to the old ones (about 5 GB while it runs), and the data, which grows with the number of hosts and VMs until it levels off after the retention periods. Estimate it like this:

```
disk (GB) = 15 + 0.08 × VMs + 0.2 × (hosts + clusters) [+ 1 × HVM hosts with the exporters]
```

| Estate | Formula | Provision |
|---|---|---|
| Lab: 3 hosts, 1 cluster, 25 VMs | 15 + 2 + 0.8 = 18 | 20 GB |
| 10 hosts, 2 clusters, 200 VMs | 15 + 16 + 2.4 = 33 | 40 GB; 50 GB with the exporters |
| 50 hosts, 5 clusters, 1,000 VMs | 15 + 80 + 11 = 106 | 120 GB; 160 GB with the exporters |

Where the numbers come from (measured in the test lab, with the default settings):

* The collector samples every minute. Each VM adds about 15,000 rows a day, each host and cluster about 38,000.
* Per-minute data is kept for 90 days (`retention.raw`). The newest 7 days stay uncompressed (about 220 bytes a row); older days are compressed about 30 times.
* Hourly averages are kept for 2 years (`retention.hourly`), about 170 bytes a row. Over time they're about half the database.
* So each VM settles at about 0.06 GB and each host or cluster at about 0.15 GB. The formula adds about a quarter on top for indexes and the other tables.
* With the optional [exporters](EXPORTERS.md), Prometheus keeps 90 days of host and VM detail: about 1 GB for each HVM host with its VMs.

Longer retention needs more: double `retention.hourly` and the 0.08 and 0.2 figures grow by about half.

### Changing the size later

* **Memory and vCPUs:** change the plan in Morpheus (reconfigure the instance) and restart the VM. At boot, TimescaleDB is tuned again for a quarter of the new memory (0.7.0 and later; before that it kept the tuning from its first boot). With a fixed `database.memory`, it keeps that size.
* **Disk:** enlarge the disk in Morpheus (reconfigure the instance), then restart the VM. At boot, cloud-init grows the root partition and file system to fill the disk, the same way it does on first boot. Tested on an HVM cluster. Take a VM snapshot first anyway, as for any disk change.
* **Starting again bigger:** provision a new, larger VM from the image and move the data with [backup and restore](INSTALL.md#backup-and-restore).

## 1. Create a read-only account in Morpheus

The same as a regular install: see [INSTALL step 1](INSTALL.md#1-create-a-reader-account-in-vme). An API token for that account is easiest for the appliance.

## 2. Import the image into Morpheus

In Morpheus, go to **Library → Virtual Images → + Add → QCOW2** ([Virtual Images](https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/library/virtual_images/virtual_images.rst)):

| Field | Value |
|---|---|
| Name | `vme-insight-<version>` |
| Operating System | Debian 13 64-bit (or the closest Debian entry) |
| Minimum Memory | 4 GB |
| Cloud Init Enabled | **On** |
| Install Agent | Your choice. vme-insight doesn't need the Morpheus agent. |
| Username / Password | Leave empty to use the global cloud-init user (Administration → Settings → Provisioning). Don't enter `root` or `debian`. |
| VirtIO Drivers Loaded | **On** |
| VM Tools Installed | **On** (the QEMU guest agent is installed) |
| File / URL | Upload the `.qcow2`, or give a URL the Morpheus appliance can reach. With a file, wait for the upload to finish before saving. |

Check the file against `SHA256SUMS` before uploading (`sha256sum -c SHA256SUMS`).

## 3. Provision a VM and pass the settings

Before you start, check two things from [Requirements](#requirements), because a VM provisioned without them has to be deleted and provisioned again:

* **The cloud-init user** is set in Administration → Settings → Provisioning → Cloud-Init Settings. It's your only way to sign in to the VM.
* **The network gives the VM an address**: DHCP, an IP pool on the network, or a static address you'll type in.

Provision an instance from the image on an HVM cluster (Provisioning → Instances → + Add, type **HVM**), with a plan sized from [Sizing](#sizing).

The appliance reads its settings from `/etc/vme-insight/appliance.yaml`. Provide them in one of these ways:

**a) With cloud-init (nothing to type in the VM).** Edit the image (Library → Virtual Images → the vme-insight image → Edit) and paste the script below into its **Cloud-Init User Data** field. Morpheus runs whatever is in that field as a shell script during the first boot of every VM provisioned from the image ([Virtual Images](https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/library/virtual_images/virtual_images.rst): "accepts what would go in runcmd and can assume Bash syntax").

The script does one thing: it writes the appliance's settings file. When cloud-init finishes, the appliance reads that file and starts vme-insight.

```bash
mkdir -p /etc/vme-insight
cat > /etc/vme-insight/appliance.yaml <<'EOF'
morpheus:
  url: https://morpheus.example.com
  api_token: 'the-read-only-token'
  tls_fingerprint: 'AA:BB:...'
EOF
chmod 600 /etc/vme-insight/appliance.yaml
```

Replace the three values:

| Setting | What to put |
|---|---|
| `url` | The Morpheus UI address, as this VM reaches it |
| `api_token` | The API token of the read-only account from step 1. Or use `username:` and `password:` instead. |
| `tls_fingerprint` | The SHA-256 fingerprint of the Morpheus certificate (see [The Morpheus certificate](#the-morpheus-certificate)). Leave it out if the certificate is publicly trusted. |

Everything between the two `EOF` lines is the settings file, so any other setting can go there too. https is on by default (port 443, answering on this VM's own addresses). For example, to give the appliance a DNS name and use a proxy, add:

```yaml
https:
  hostname: vme-insight.example.com 10.0.0.25
proxy:
  url: http://proxy.example.com:3128
```

List every name and IP people will type (see [Names and addresses](#names-and-addresses)). To leave https off, use `enabled: false` under `https:` instead.

All the settings, with comments, are in `/etc/vme-insight/appliance.yaml.example` in the VM, or [appliance/rootfs/etc/vme-insight/appliance.yaml.example](../appliance/rootfs/etc/vme-insight/appliance.yaml.example).

The field belongs to the image, so every VM provisioned from it gets the same settings. The token ends up in the VM's cloud-init data, readable by root only. That's another reason to use a read-only account.

**b) Interactively.** Without user data, the appliance boots, loads its images and waits. SSH in with the user Morpheus injected and run:

```bash
sudo vme-insight-setup
```

It asks for the Morpheus URL and the read-only token (or username and password). It shows the Morpheus certificate's SHA-256 fingerprint so you can pin it, then asks about https and starts vme-insight.

### The Morpheus certificate

A Morpheus appliance with a self-signed certificate needs `tls_fingerprint`: the SHA-256 fingerprint of that certificate. `vme-insight-setup` shows it. To get it on any machine first:

```bash
openssl s_client -connect morpheus.example.com:443 </dev/null 2>/dev/null | openssl x509 -noout -fingerprint -sha256
```

Compare it with what your browser shows for the Morpheus UI before trusting it. If your own CA signed the certificate, set `ca_pem` to that CA's PEM instead.

## 4. Open the dashboards

* `https://<vm-address>`: Grafana over https on port 443, limited to the networks you allowed. User `admin`, password from `sudo vme-insight-setup --show-password`. https is on by default; the first time, the browser warns about the appliance's own certificate unless you gave it yours (`https.cert_pem` and `key_pem`). An appliance set up with https on 3443 keeps that port: `https://<vm-address>:3443`.
* `http://<vm-address>:3000`: plain http, open unless you close it. The wizard also asks whether to close plain http on 3000, and whether to allow [vme-insight-plugin](VME-PLUGIN.md) to embed the dashboards in the Morpheus UI.

### Names and addresses

The https front end answers only for the names and IPs in its list, and shows an empty page for any other address. Leave the list empty (press Enter in the wizard) and the appliance uses its own IP addresses and host name, found again at each boot, so a new DHCP address works too. If people use a DNS name, list it together with the IP: `vme-insight.example.com 10.0.0.25`. Appliances before 0.6.1 used only `localhost` when the list was empty, which gave an empty page; 0.6.1 fixes that.

### Your own certificate

Out of the box, the https front end uses a certificate from its own internal CA, so browsers warn the first time. To use a certificate browsers already trust, or one you can check and import, give the appliance your own. List every name and IP people type in the names list first ([Names and addresses](#names-and-addresses)), and put the same names in the certificate.

* **A certificate from your organization's CA, or a public one.** Put it (leaf first, then any intermediates) and its key in `/etc/vme-insight/appliance.yaml`, then run `sudo vme-insight-apply`:

  ```yaml
  https:
    cert_pem: |
      -----BEGIN CERTIFICATE-----
      ...
    key_pem: |
      -----BEGIN PRIVATE KEY-----
      ...
  ```

* **A self-signed certificate for this VM only, or one from your own name-limited CA.** `make-cert.sh` makes it on the VM and puts it in `appliance.yaml` for you. Run it with `sudo`, because `/opt/vme-insight` belongs to root:

  ```bash
  sudo /opt/vme-insight/tools/make-cert.sh host vme-insight.example.com 10.0.0.25
  sudo vme-insight-apply
  ```

  It prints the certificate's SHA-256 fingerprint, to check before you import `vme-insight.crt` on each browser machine. The options and the CA variant (`ca --permit ...`, which keeps its CA in `/root/vme-insight-ca`) are described in [VME-PLUGIN: Make browsers trust the certificate](VME-PLUGIN.md#3-make-browsers-trust-the-certificate). In 0.7.0 and earlier, `make-cert.sh` doesn't know about the appliance: it prints steps for `.env`, which the appliance rewrites. If you made the files that way, copy them into `appliance.yaml` like this, then run `sudo vme-insight-apply`:

  ```bash
  sudo python3 -c 'import yaml; p="/etc/vme-insight/appliance.yaml"; s=yaml.safe_load(open(p)) or {}; h=s.setdefault("https", {}); d="/opt/vme-insight/https/certs/"; h["cert_pem"]=open(d+"vme-insight.crt").read(); h["key_pem"]=open(d+"vme-insight.key").read(); yaml.safe_dump(s, open(p, "w"), sort_keys=False)'
  ```

Running the wizard again keeps your certificate. To go back to the internal CA, delete `cert_pem` and `key_pem` from `appliance.yaml` and run `sudo vme-insight-apply`. Don't set `HTTPS_TLS` in `/opt/vme-insight/.env`: the appliance writes that file from `appliance.yaml` at every boot and apply.

### The https port

The wizard asks which port https uses:

* **443**, the standard https port, is the wizard's default for a new appliance. People type `https://vme-insight.example.com` with no port number, and firewalls and proxies usually allow it already.
* **3443** is what earlier releases used. An appliance set up with https before 0.6.1 keeps 3443, both when you run the wizard again and in its settings file, unless `https.port` says otherwise.

**Changing the port on an appliance that's in use:** in the same sitting, change it on the appliance (`sudo vme-insight-setup`), then in the Morpheus UI set the plugin's **vme-insight Grafana URL** to match (see [VME-PLUGIN: the https port](VME-PLUGIN.md#changing-the-https-port)). Also update `grafana.root_url` if you set it, firewall or security group rules for the new port, proxy exceptions that include the port, and bookmarks. Until the plugin setting matches, the vme-insight tabs in Morpheus show an empty or blocked frame. Nothing else in Morpheus is affected.

The first data appears after a minute or two. The login message shows the status, and so does `sudo vme-insight-setup --status`.

## Changing settings

Run the wizard again:

```bash
sudo vme-insight-setup
```

It shows the current value of each setting in [brackets], so press Enter for the ones you're keeping. It covers the Morpheus URL, account and certificate, the time zone, https, the proxy, the time and DNS servers, the daily update check and the database's memory, and it keeps any other settings in the file. When you finish, it applies the changes and restarts what needs it.

For the few settings it doesn't ask about (your own https certificate (see [Your own certificate](#your-own-certificate)), your own CA for Morpheus, the Grafana port), edit `/etc/vme-insight/appliance.yaml` (every setting is described in `/etc/vme-insight/appliance.yaml.example`), then run `sudo vme-insight-apply`.

The appliance writes `.env` and the `morpheus` section of `/opt/vme-insight/config/config.yaml` from the settings file at every boot and every apply, so don't edit those by hand. The rest of `config.yaml` (retention, intervals, lifecycle rules) is yours to edit as in a regular install ([CONFIGURATION](CONFIGURATION.md)). Then run `sudo docker compose restart collector` in `/opt/vme-insight`.

> **0.5.0 only:** the wizard keeps just the settings it asks about and the update check, and every boot resets `config.yaml` to the example. If you changed either by hand, make the change again after running the wizard or rebooting. Later releases keep both.

## Changing passwords

The appliance generates three passwords at first boot and keeps them in `/opt/vme-insight/.env` (readable by root only): Grafana's `admin` user, and two database users that only the containers use. Nobody needs to know the database ones, but you can change any of them. The steps are the same as for a regular install: see [INSTALL: Changing passwords](INSTALL.md#changing-passwords). On the appliance, run them in `/opt/vme-insight` with `sudo` in front of each `docker` and `sed` command.

For the Morpheus account's password or token, run `sudo vme-insight-setup` again.

## Keeping it up to date

The appliance has two parts that update separately:

* **Debian (the operating system, Docker and the other packages).** Patch it the way you patch any Debian 13 server: your own tooling, `unattended-upgrades`, or `sudo apt update && sudo apt upgrade` and a reboot when the kernel changes. vme-insight doesn't manage this, and an apt upgrade doesn't change vme-insight or its container images.
* **vme-insight and its container images (TimescaleDB, Grafana, Prometheus, Caddy, the collector).** apt never touches these. Update them with:

  ```bash
  sudo vme-insight-update
  ```

  It checks GitHub for a newer release and, after you confirm, replaces the vme-insight files and the appliance's own scripts and services, pulls the new container images, rebuilds the collector, updates the Grafana treemap plugin if the release changes it, and restarts. Your settings, passwords and data stay. **Take a snapshot of the VM in Morpheus first**: that's your rollback. It needs internet access to github.com, grafana.com and the container registries (Docker Hub). A release that changes the PostgreSQL major version stops with a message instead, because that needs a dump and restore (see the release notes). `sudo vme-insight-update --force` reinstalls the current release, to repair changed or deleted files.

**Updating from 0.6.0 or earlier:** those releases' `vme-insight-update` replaced the vme-insight files but not the appliance's own scripts (`vme-insight-setup`, `vme-insight-apply`, `vme-insight-update` and the services), so fixes to them never arrived. After updating, install them once:

```bash
sudo sh /opt/vme-insight/appliance/install-system-files.sh && sudo vme-insight-apply
```

From 0.6.1 on, `vme-insight-update` does this itself. Your https setting doesn't change: an appliance that ran without https keeps it off until you turn it on with `sudo vme-insight-setup`.

Once a day the appliance checks GitHub for a new release (read only; it installs nothing). When there is one, the login message says so. To turn the check off, answer No to the update question in `sudo vme-insight-setup`, or add this to `/etc/vme-insight/appliance.yaml` and run `sudo vme-insight-apply`:

```yaml
updates:
  check: false
```

Without internet access, or to start fresh, provision a VM from the new release's image instead and move the history with [backup and restore](INSTALL.md#backup-and-restore). Each release ships a new image, built with the Debian updates available at release time.

## Building the image yourself

From a checkout of this repository, on any Linux host with Docker and internet access (no KVM needed, but it is faster with it):

```bash
appliance/build.sh
```

The build:
1. Downloads the Debian 13 cloud image and checks it against Debian's `SHA512SUMS`.
2. Saves the container images that `docker-compose.yml` uses.
3. Installs Docker and the appliance scripts with `virt-customize`.
4. Writes `appliance/build/out/vme-insight-appliance-<version>.qcow2` and `SHA256SUMS`.

Only files git tracks go into the image, so your `.env`, `config.yaml` and certificates stay out.

To test an image, `appliance/test/boot-test.sh` boots it under QEMU with a cloud-init seed, the same way Morpheus does. `appliance/test/check.sh` checks it. With `ISOLATED=1`, the VM's only way out is a logging test proxy (plus a direct path to Morpheus), and `appliance/test/check-proxy.sh` shows that every download goes through the proxy.

## Troubleshooting

| Symptom | Check |
|---|---|
| Login message says "not configured" | No settings arrived. Run `sudo vme-insight-setup`, or check that the user data wrote `/etc/vme-insight/appliance.yaml`. |
| "failed" in the status | `journalctl -u vme-insight-firstboot` |
| Grafana up but no data | `cd /opt/vme-insight && sudo docker compose logs collector`. A wrong token, URL or fingerprint shows there. See [TROUBLESHOOTING](TROUBLESHOOTING.md). |
| Provisioning fails with "Image is not in qcow2 format" | The HVM host downloads the image from Morpheus's **Appliance URL** (Administration → Settings → Appliance). The hosts must reach that URL directly: if it is a name behind a login proxy such as Cloudflare Access, they save the login page instead of the image. Use an address the hosts can reach, or set the **Internal Appliance URL**. Then delete the image and import it again, because each host keeps its bad copy. |
| Grafana's login page comes back after you sign in, as if the password were wrong | Images before 0.5.0 marked the sign-in cookie Secure whenever https was on, and browsers don't keep a Secure cookie on plain `http://…:3000`. Use `https://…:3443`, or run `sudo vme-insight-apply` after updating. The cookie is now Secure only with `https.only: true`, which also closes port 3000. |
| The browser can't open the dashboards, but `Test-NetConnection <vm-address> -Port <https port>` (PowerShell) says `TcpTestSucceeded : True` | The browser is probably sending the request through your organization's web proxy, which can't reach the appliance. To confirm, run `curl.exe -k --noproxy "*" -s -o NUL -w "%{http_code}" https://<vm-address>:<https port>/login` in PowerShell: `200` means the appliance is fine. Add the appliance's **exact address** (for example `10.0.0.25`) to the browser's or system's proxy exceptions. A subnet or wildcard exception such as `10.0.*` may not be enough, because some proxy setups ignore those for plain IP addresses. |
| `https://<vm-address>` opens an empty white page (after any certificate warning) | The address you typed isn't in the appliance's names list ([Names and addresses](#names-and-addresses)). Check with `sudo grep ^HTTPS_HOSTNAME= /opt/vme-insight/.env`. Run `sudo vme-insight-setup` and press Enter at the names question to use the VM's own addresses, or list every name and IP people type. |
| Can't sign in to the VM | The appliance has no password login. Use the SSH key or user from Morpheus's cloud-init settings. |
