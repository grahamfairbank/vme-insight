# Exporters on HVM hosts (optional)

The VME API reports about one sample per minute of CPU, memory, storage, network, IOPS and CPU ready. Two small agents on each HVM host add much more:

> **Where to run the commands on this page:** in the vme-insight folder. On the [appliance](APPLIANCE.md) that's `/opt/vme-insight` (`cd /opt/vme-insight`), and each `docker` and `tools/` command needs `sudo` in front. For a Docker Compose install it's the folder you cloned into, such as `~/vme-insight`.

| Exporter | Port | Adds |
|---|---|---|
| [`node_exporter`](https://github.com/prometheus/node_exporter) (official release binary) | 9100 | Host CPU by mode, load, memory and swap detail, **pressure stall information (PSI)**, **per-mount filesystem space, inodes and read-only state**, per-disk IOPS, latency and busy time, per-NIC traffic, drops and errors, uptime |
| [`prometheus-libvirt-exporter`](https://github.com/inovex/prometheus-libvirt-exporter) (inovex) | 9177 | Per VM: state, vCPUs, CPU time, **vCPU wait (delay)**, RSS, balloon/swap/page-fault stats, per-disk requests and latency, per-interface traffic and drops |

Prometheus in the stack scrapes them every 30 seconds. The three **(exporters)** dashboards use them, as do the **Local filesystems** panels on VME Hosts. The VME API reports only one storage total per host, so per-mount filesystem monitoring needs node_exporter.

## Before you start

* **Support.** These packages aren't part of VME. Check that adding packages to your hypervisors is acceptable under your HPE support terms. Both are read-only and lightweight (a few MB of RAM and well under 1% CPU).
* **Network.** Neither exporter has authentication. Bind them to the management address and allow 9100 and 9177 only from the vme-insight host.

## Install

The installer runs **on each HVM host** and fetches what it needs from the vme-insight server, so you don't need to copy files around or give vme-insight SSH access to your hypervisors.

**1. On the vme-insight host**, download the exporter packages (checksum-verified against their GitHub releases) and start the installer service.

On the **appliance**, sign in to the VM and run, from any folder:

```bash
cd /opt/vme-insight
sudo ./tools/fetch-exporter-packages.sh
sudo docker compose --profile installer up -d installer
```

For a **Docker Compose install**, run the same in the folder you cloned into (such as `~/vme-insight`), with `sudo` only if your user isn't in the `docker` group.

`fetch-exporter-packages.sh` downloads from GitHub, so the vme-insight host needs internet access for this step, directly or through a proxy. On the appliance it uses the proxy set in `appliance.yaml` (see [APPLIANCE: Proxy](APPLIANCE.md#proxy)); a proxy already in your environment, such as one in `/etc/environment`, is used as it is. Without internet access, download the two files named in the script on another machine and copy them into `installer/dist/`.

The installer service is a small static web server on port `INSTALLER_PORT` (default 8097). It serves `install-exporters.sh` with its own address filled in, plus the package from `installer/dist/`.

**2. On each HVM host**, as a user with sudo, run:

```bash
curl -fsSL http://<vme-insight-host>:8097/install-exporters.sh | sudo bash
```

The command is the same on every host. The HVM host needs to reach the vme-insight host on TCP 8097 only; it needs no internet access when step 1 succeeded.

* **`Failed to connect … port 8097 … Couldn't connect to server`** although the vme-insight host answers ping: the installer service isn't running. Run step 1 again on the vme-insight host and check that `sudo docker compose ps installer` (in `/opt/vme-insight`) shows it running.
* **A proxy on the HVM host:** if the host has `http_proxy` set (for example in `/etc/environment`, which `sudo` passes on), add the vme-insight host's address to its `no_proxy`, or the downloads from port 8097 go to the proxy. For one run: `curl -fsSL http://<vme-insight-host>:8097/install-exporters.sh | sudo no_proxy=<vme-insight-host> bash`.

The script:

1. Works out the host's **management IP** (the address it uses to reach the vme-insight server) and binds both exporters to it only. To choose another address, add `-s -- --listen <ip>` after `bash`.
2. Installs **node_exporter** from the official Prometheus release to `/usr/local/bin/node_exporter`, as the systemd service `vme-node-exporter`. HVM hosts get their packages from HPE's repositories, which don't include node_exporter, so the script doesn't use apt at all and never runs `apt-get update` on your hosts.
3. Installs the libvirt exporter `.deb` with `dpkg`. Both downloads come from the vme-insight server, or from GitHub if they aren't there, and both are checked against **SHA-256 hashes pinned in the script** before anything is installed, so a tampered mirror can't slip in a different file.
4. Adds a systemd drop-in so the libvirt exporter runs as an unprivileged dynamic user with only the `libvirt` group, instead of root.
5. Enables and starts both, then prints a self-check.

Example output from an HVM host (VME 9.1, Ubuntu 26.04):

```
hvmadmin@hvm01:~$ curl -fsSL http://192.168.13.250:8097/install-exporters.sh | sudo bash

== host hvm01, exporters will listen on 192.168.13.100

== node_exporter 1.12.1
node_exporter-1.12.1.linux-amd64.tar.gz: downloaded from http://192.168.13.250:8097/dist, sha256 verified

== libvirt exporter 2.6.1
prometheus-libvirt-exporter-2.6.1.amd64.deb: downloaded from http://192.168.13.250:8097/dist, sha256 verified

== checks
vme-node-exporter              active
prometheus-libvirt-exporter    active
node_* series on :9100:        796
VMs seen by libvirt on :9177:  1
Done. vme-insight will start scraping this host within a minute.
```

How to read it:

| Line | Check |
|---|---|
| `exporters will listen on` | Should be the host's management IP. If not, re-run with `-s -- --listen <ip>` after `bash`. |
| `downloaded from ..., sha256 verified` | Both files passed the pinned hash check. `downloaded from https://github.com/...` means the vme-insight server didn't have them (run `fetch-exporter-packages.sh` there). |
| `active` | Both services are running |
| `node_* series` | Several hundred is normal. The exact number depends on the host's CPUs, disks and NICs. |
| `VMs seen by libvirt` | The number of VMs running on this host right now. `0` is fine on an empty host. |

   It exits with an error and the `journalctl` command to run if either service didn't come up.

Running it again is safe. It reinstalls and restarts with the same settings.

**3. When all hosts are done**, you can stop the installer service: `docker compose --profile installer stop installer`.

**Without the installer service:** copy `tools/install-exporters.sh` to the host and run `sudo ./install-exporters.sh --listen <management-ip>`. It downloads both from GitHub, so the host needs outbound HTTPS.

**Upgrading the exporters:** neither is updated by apt. On the vme-insight host run `./tools/fetch-exporter-packages.sh <node_exporter version> <libvirt exporter version>`, then on each host `curl … | sudo bash -s -- --node-version <v> --libvirt-version <v>`. Versions without a pinned hash are checked against their release's checksum file. New releases of vme-insight update the pinned versions.

### Firewall

HVM hosts may run a firewall that the HVM image and your site's policy own. HPE warns not to assume what disabling or changing UFW does on an HVM host, because cluster quorum, storage and migration traffic depend on those rules ([Host Firewall Ownership](https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/getting_started/installation/hvm_host_prep.rst)). So:

* **Never disable the firewall** to make the exporters reachable.
* Add one narrow allow rule, approved per your site's process, for TCP 9100 and 9177 from the vme-insight host only. With UFW that's:

  ```bash
  sudo ufw allow from <vme-insight-host-ip> to any port 9100,9177 proto tcp
  ```

* On the VME manager only port 9100 is needed.

## The VME manager

The same installer works inside the **VME manager VM**. It detects that there's no libvirt and installs node_exporter only:

```bash
curl -fsSL http://<vme-insight-host>:8097/install-exporters.sh | sudo bash
```

```
hvmadmin@vmemanager:~$ curl -fsSL http://192.168.13.250:8097/install-exporters.sh | sudo bash

== host vmemanager, exporters will listen on 192.168.13.103

== node_exporter 1.12.1
node_exporter-1.12.1.linux-amd64.tar.gz: downloaded from http://192.168.13.250:8097/dist, sha256 verified
no libvirt on this host: installing node_exporter only

== checks
vme-node-exporter              active
node_* series on :9100:        468
Done. vme-insight will start scraping this host within a minute.
```

This fills the **Manager VM detail** row on the Manager & Collector dashboard: CPU, memory, pressure stall, every filesystem and disk latency. Without it, the **Manager resources** row still shows disk, memory and swap from the VME API. The manager is an HPE appliance, so check your support terms before adding software to it.

## Guest memory

With the libvirt exporter, the [memory right-sizing](DASHBOARDS.md#memory-right-sizing) panels on VME Virtual Machines also use each guest's own memory figure from the virtio balloon statistics: memory the guest sees minus what it could still use (its page cache doesn't count), and how fast it swaps out. The collector reads these back from Prometheus every minute (`exporters.prometheus_url`) and stores them with the VM's other metrics.

libvirt refreshes balloon statistics only while the VM's balloon has a statistics period. Readings older than 5 minutes are ignored, so a VM is never sized from a stale figure. To see whether a VM's figures are fresh, on its HVM host:

```bash
sudo virsh dommemstat <vm-name>
```

`last_update` is a Unix time; if it's old, the period isn't set. `sudo virsh dommemstat <vm-name> --period 60 --live` turns it on until the VM restarts. Whether to set it, and how to keep it, is a change to how the VM runs on your HVM hosts: check your HPE support terms first. Without fresh libvirt figures, right-sizing uses the figure Morpheus reports (which needs the QEMU guest agent in the VM).

## Discovery

You don't edit `prometheus.yml`. The collector writes `hvm-node.json` and `hvm-libvirt.json` target files from the hosts VME reports, every minute, plus `vme-manager.json` for the manager (the host in `morpheus.url`, or `exporters.manager_address`). Hosts added to or removed from VME appear in or disappear from Prometheus by themselves. Each target carries these labels:

| Label | Value |
|---|---|
| `nodename` | Host name in VME |
| `cluster` | Cluster name in VME |
| `vme_host_id` | Host id in VME (matches `servers.id` in TimescaleDB) |
| `source` | `exporters.source` from config (default `vme`) |
| `instance` | Host address without the port, so node and libvirt series join |

The address scraped is the host's internal IP by default. See `exporters.address` in [CONFIGURATION](CONFIGURATION.md#exporters).

## Check

Prometheus has no published port by default. To look at target health, uncomment its `ports:` block in `docker-compose.yml`, run `docker compose up -d prometheus` and open `http://127.0.0.1:9091/targets`. Or ask from inside the stack:

```bash
docker compose exec prometheus wget -qO- 'http://localhost:9090/api/v1/targets?state=active' \
  | python3 -c 'import json,sys; [print(t["labels"]["job"], t["labels"]["nodename"], t["health"], t["lastError"]) for t in json.load(sys.stdin)["data"]["activeTargets"]]'
```

`down` with `connection refused` means the exporter isn't running or is bound to another address. A timeout means a firewall is in the way.

## Datastore and VM names

The collector also publishes a small Prometheus endpoint (`collector:9105/metrics`, job `vme-info`) with VME names for exporter series:

* `vme_datastore_info{mountpoint, datastore, datastore_type, datastore_id}`: maps a host mount point such as `/mnt/0cf9aa96-…` to the VME datastore `silo`. The filesystem panels use it to show datastore names.
* `vme_vm_info{domain, vm, vm_id, vme_host}`: maps a libvirt domain to the VME VM.

Join them in your own queries, for example:

```promql
node_filesystem_avail_bytes * on (mountpoint) group_left (datastore) vme_datastore_info
```

## VM names

In HVM, the libvirt domain name is the VM's name in VME, so the `domain` label lines up with VM names on the API dashboards.

## Removing

```bash
sudo systemctl disable --now vme-node-exporter prometheus-libvirt-exporter
sudo rm /etc/systemd/system/vme-node-exporter.service /usr/local/bin/node_exporter
sudo dpkg -r prometheus-libvirt-exporter
sudo rm -rf /etc/systemd/system/prometheus-libvirt-exporter.service.d
```
