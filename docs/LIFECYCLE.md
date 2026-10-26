# OS lifecycle and agent currency

The **VME Inventory & Lifecycle** dashboard answers four questions for every host and VM: is its OS still supported, is it on the latest point release, is the Morpheus agent current, and is the QEMU guest agent running.

## Where the data comes from

* **What each server runs** comes from the VME API: `serverOs.name`, `platform`, `platformVersion` and `osType`. Hosts always report this. **VMs report a specific OS only when the Morpheus agent or the QEMU guest agent is running in the guest.** Otherwise VME knows only something like "linux 64-bit", and the VM shows as `unknown os`.
* **Lifecycle dates** come from [endoflife.date](https://endoflife.date), once a day: release date, end of active support, end of life, and latest point release for each release cycle. The collector fetches the products it sees in your estate plus Ubuntu, RHEL, Rocky, AlmaLinux, Debian and Windows Server.

## Matching an OS to a product

The collector turns the OS text into an endoflife.date product and release cycle:

| OS text contains | Product | Cycle example |
|---|---|---|
| ubuntu | `ubuntu` | `24.04` |
| red hat / rhel | `rhel` | `9` |
| rocky | `rocky-linux` | `9` |
| alma | `almalinux` | `9` |
| centos stream / centos | `centos-stream` / `centos` | `9` / `7` |
| oracle | `oracle-linux` | `9` |
| debian | `debian` | `12` |
| sles / suse linux enterprise | `sles` | `15.5` (from "15 SP5") |
| opensuse, fedora, amazon, freebsd | matching product | |
| windows server | `windows-server` | `2022`, `2012-r2` |
| windows | `windows` | `11` |

Anything else lands in the **Unrecognized OS strings** panel. Add a rule for it in `lifecycle.os_rules` ([CONFIGURATION](CONFIGURATION.md#lifecycle)).

## OS status

Checked in this order:

| Status | Meaning |
|---|---|
| `unknown os` | VME doesn't report a recognisable OS (usually: no agent in the guest) |
| `unknown release` | The product is known but the release cycle isn't in endoflife.date |
| `end of life` | The end-of-life date has passed |
| `eol < 180d` | End of life within 180 days |
| `update available` | The server reports a point release (for example `22.04.3`) older than the latest in its cycle (`22.04.5`). If VME reports only the cycle (`26.04`), this check is skipped rather than guessed. |
| `current` | None of the above |

## Morpheus agent status

| Status | Meaning |
|---|---|
| `not installed` | VME reports no agent. Normal for VMs that don't use it; hosts always have one. |
| `outdated` | Older than the target version |
| `current` | At or above the target version |

The **target version** is `lifecycle.expected_agent_version` from config, or if that's blank, the newest agent version seen anywhere in the estate. After an upgrade, hosts that haven't picked up the new agent show as outdated. The **Agent check-in** column shows when VME last heard from each agent.

## QEMU guest agent

VME reports `guestAgentStatus` per VM: `connected`, `disconnected` or `unknown`. Since 9.1.0, VME uses the QEMU Guest Agent to gather the guest's IP addresses, OS version and hostname without network access ([9.1.0 release notes](https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/release_notes/9_1_0.rst)). A running VM without a connected guest agent therefore can't report its OS, which is the usual reason for `unknown os`. It also can't be shut down gracefully or customized (Sysprep on Windows), so the dashboard counts these separately, and VME raises a *VM Guest Agent Not Responding* alarm. For Windows, the agent comes with `virtio-win-guest-tools` ([guest OS notes](https://github.com/HewlettPackard/morpheus-docs/blob/dev-9.1/infrastructure/clusters/hvm/guest_os_notes.rst)). On Linux, install and enable the distribution's `qemu-guest-agent` package.

## VME itself

The manager version is shown on the Overview and Lifecycle dashboards. There's no public feed of the latest VME release, so the dashboard shows the version for you to compare against HPE's [release notes](https://github.com/HewlettPackard/morpheus-docs/tree/dev-9.1/release_notes). The collector logs a warning if the manager is older than the supported 9.1.

## Change log

Every update to a host or VM row is compared field by field by a database trigger, and differences are written to `inventory_changes`. This covers OS and platform version, agent and guest agent, power state, status, vCPU, memory, disk, host (live migration), cluster, maintenance mode, IP, and discovery or removal. Use it to answer "when was this VM resized?" or "which hosts got the new agent last night?".
