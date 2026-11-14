# vme-insight virtual appliance

A ready-to-run virtual machine image of vme-insight for HPE Morpheus VM Essentials. Import it as a virtual image, provision a VM from it on an HVM (HPE Virtual Machine) cluster, give it the Morpheus URL and a read-only account, and the dashboards start. Nothing else to install: Docker, vme-insight and every container image it needs are inside, so it works without internet access.

* **Image:** `vme-insight-appliance-<version>.qcow2` (QCOW2, compressed), with `SHA256SUMS`.
* **Inside:** Debian GNU/Linux 13 cloud image, Docker and Docker Compose from Debian, the QEMU guest agent, cloud-init, vme-insight in `/opt/vme-insight`, and its container images (TimescaleDB, Grafana with the treemap panel, Prometheus, Caddy, the collector).
* **No accounts or passwords in the image.** You sign in with the SSH key or user Morpheus injects through cloud-init. The database and Grafana passwords are generated on each VM at first boot.

> **Community project.** Not affiliated with, endorsed, sponsored or supported by Hewlett Packard Enterprise, Morpheus Data, or the Debian Project. Third-party licenses: `/usr/share/doc/vme-insight-appliance/NOTICE` in the VM.

## Requirements

What the appliance needs from Morpheus and the network, and what it doesn't:

| | Needed? | Details |
|---|---|---|
| **Cloud-init credentials in Morpheus** | **Yes, to sign in** | Administration → Settings → Provisioning → Cloud-Init Settings: a username and an SSH key pair (or password). Morpheus injects them through cloud-init. The image has no password or default login of its own, so without these you can't sign in. The dashboards still start if the settings arrive through user data. |
| **Storage** | Any datastore | The VM sees an ordinary virtio disk, wherever the HVM cluster keeps it: a GFS2 datastore on external block storage, local storage or anything else. The appliance needs **no NFS**. It doesn't mount shared storage, and all its data (database, Grafana) is on its own disk. The NFS client isn't installed. |
| **Network address** | DHCP or a Morpheus IP pool | Cloud-init applies the network settings Morpheus puts on the provisioning ISO, so static addresses from an IP pool should work as well as DHCP. Tested so far with DHCP only. |
| **DNS** | If the Morpheus URL is a name | Cloud-init sets the DNS servers from the network settings. With `url: https://<ip>` the appliance needs no DNS for its core job. |
| **Time (NTP)** | Yes | Accurate time matters for the charts and for TLS. The appliance uses `systemd-timesyncd`, which by default asks Debian's public pool (`*.debian.pool.ntp.org`, UDP 123). Without internet access, point it at your own time servers (below). |
| **To Morpheus** | Yes | HTTPS (443) from the appliance to the Morpheus appliance, with a read-only account. |
| **From users** | Yes | TCP 3000 (Grafana) or 3443 (https front end) from the people and the Morpheus UI that view the dashboards. Optionally SSH (22) for administration. |
| **To HVM hosts** | Only with the exporters | TCP 9100 and 9177 to each HVM host, if you install the optional [exporters](EXPORTERS.md). |
| **Internet** | Optional | Only `endoflife.date` (HTTPS, daily) for OS end-of-life data, `api.github.com` (HTTPS, daily) for the update notice, `vme-insight-update` when you run it, plus Debian updates and NTP if you use the defaults. Container images and the Grafana plugin are already in the image, so nothing is downloaded from Docker Hub or grafana.com. Without internet, everything works except end-of-life dates on the Lifecycle dashboard. |
| **Morpheus agent** | No | Choose either way when importing. vme-insight reads everything through the Morpheus API. |

### Your own time servers

Add this to the same Cloud-Init User Data as the settings, with your servers:

```bash
mkdir -p /etc/systemd/timesyncd.conf.d
printf '[Time]\nNTP=ntp1.example.com ntp2.example.com\n' > /etc/systemd/timesyncd.conf.d/local.conf
systemctl restart systemd-timesyncd
```

Check with `timedatectl timesync-status`.

## Sizing

| | Minimum | Recommended |
|---|---|---|
| vCPU | 2 | 4 |
| Memory | 4 GB | 8 GB |
| Disk | 20 GB | 40 GB or more for larger estates |

The root disk grows to the size you provision at first boot. For scale: in the test lab, 28 hosts and VMs filled about 1 GB of database in three weeks. Per-minute samples are kept 90 days (`retention.raw`) and compressed after 7, so the database levels off rather than growing forever.

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

Provision an instance from the image on an HVM cluster (Provisioning → Instances → + Add, type **HVM**), with a plan that has at least 4 GB of memory.

The appliance reads its settings from `/etc/vme-insight/appliance.yaml`. Provide them in one of these ways:

**a) With cloud-init user data (no login needed).** Morpheus delivers cloud-init to HVM VMs on a NoCloud ISO ([HVM guest notes](https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/infrastructure/clusters/hvm/guest_os_notes.rst)). Put this in the image's **Cloud-Init User Data** field, or in a cloud-init script under Library → Templates → Scripts selected at provisioning:

```bash
mkdir -p /etc/vme-insight
cat > /etc/vme-insight/appliance.yaml <<'EOF'
morpheus:
  url: https://morpheus.example.com
  api_token: 'the-read-only-token'
  tls_fingerprint: 'AA:BB:...'      # see below; or leave empty if the certificate is publicly trusted
EOF
chmod 600 /etc/vme-insight/appliance.yaml
```

The appliance waits for cloud-init to finish, then applies the settings and starts. The token ends up in the VM's cloud-init data, readable by root only. That's another reason to use a read-only account.

**b) Interactively.** Without user data, the appliance boots, loads its images and waits. SSH in with the user Morpheus injected and run:

```bash
sudo vme-insight-setup
```

It asks for the Morpheus URL and the read-only token (or username and password). It shows the Morpheus certificate's SHA-256 fingerprint so you can pin it, then asks about https and starts vme-insight.

Every setting, with comments: `/etc/vme-insight/appliance.yaml.example` in the VM, or [appliance/rootfs/etc/vme-insight/appliance.yaml.example](../appliance/rootfs/etc/vme-insight/appliance.yaml.example).

### The Morpheus certificate

A Morpheus appliance with a self-signed certificate needs `tls_fingerprint`: the SHA-256 fingerprint of that certificate. `vme-insight-setup` shows it. To get it on any machine first:

```bash
openssl s_client -connect morpheus.example.com:443 </dev/null 2>/dev/null | openssl x509 -noout -fingerprint -sha256
```

Compare it with what your browser shows for the Morpheus UI before trusting it. If your own CA signed the certificate, set `ca_pem` to that CA's PEM instead.

## 4. Open the dashboards

* `http://<vm-address>:3000`: Grafana. User `admin`, password from `sudo vme-insight-setup --show-password`.
* With `https.enabled: true`: `https://<vm-address>:3443`, limited to the networks in `https.allow`. Use this, with `grafana.vme_plugin: true`, for [vme-insight-plugin](VME-PLUGIN.md).

The first data appears after a minute or two. The login message shows the status, and so does `sudo vme-insight-setup --status`.

## Changing settings

Edit `/etc/vme-insight/appliance.yaml` (or run `sudo vme-insight-setup` again), then run:

```bash
sudo vme-insight-apply
```

The appliance writes `/opt/vme-insight/config/config.yaml` and `.env` from that file, so make changes there rather than in those two files. Anything the settings file doesn't cover (retention, intervals, lifecycle rules) can still be edited in `/opt/vme-insight/config/config.yaml` as in a regular install. It is kept unless you change `appliance.yaml` and run apply again.

## Keeping it up to date

The appliance has two parts that update separately:

* **Debian (the operating system, Docker and the other packages).** Patch it the way you patch any Debian 13 server: your own tooling, `unattended-upgrades`, or `sudo apt update && sudo apt upgrade` and a reboot when the kernel changes. vme-insight doesn't manage this, and an apt upgrade doesn't change vme-insight or its container images.
* **vme-insight and its container images (TimescaleDB, Grafana, Prometheus, Caddy, the collector).** apt never touches these. Update them with:

  ```bash
  sudo vme-insight-update
  ```

  It checks GitHub for a newer release and, after you confirm, replaces the vme-insight files, pulls the new container images, rebuilds the collector, updates the Grafana treemap plugin if the release changes it, and restarts. Your settings, passwords and data stay. **Take a snapshot of the VM in Morpheus first**: that's your rollback. It needs internet access to github.com, grafana.com and the container registries (Docker Hub). A release that changes the PostgreSQL major version stops with a message instead, because that needs a dump and restore (see the release notes).

Once a day the appliance checks GitHub for a new release (read only; it installs nothing). When there is one, the login message says so. To turn the check off, add this to `/etc/vme-insight/appliance.yaml`:

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

To test an image, `appliance/test/boot-test.sh` boots it under QEMU with a cloud-init seed, the same way Morpheus does.

## Troubleshooting

| Symptom | Check |
|---|---|
| Login message says "not configured" | No settings arrived. Run `sudo vme-insight-setup`, or check that the user data wrote `/etc/vme-insight/appliance.yaml`. |
| "failed" in the status | `journalctl -u vme-insight-firstboot` |
| Grafana up but no data | `cd /opt/vme-insight && sudo docker compose logs collector`. A wrong token, URL or fingerprint shows there. See [TROUBLESHOOTING](TROUBLESHOOTING.md). |
| Provisioning fails with "Image is not in qcow2 format" | The HVM host downloads the image from Morpheus's **Appliance URL** (Administration → Settings → Appliance). The hosts must reach that URL directly: if it is a name behind a login proxy such as Cloudflare Access, they save the login page instead of the image. Use an address the hosts can reach, or set the **Internal Appliance URL**. Then delete the image and import it again, because each host keeps its bad copy. |
| Can't sign in to the VM | The appliance has no password login. Use the SSH key or user from Morpheus's cloud-init settings. |
