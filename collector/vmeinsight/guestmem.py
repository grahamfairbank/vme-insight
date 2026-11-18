"""Guest memory use per VM from the libvirt exporter, stored with the other VM metrics.

The libvirt exporter (optional, on each HVM host) reports the virtio balloon statistics the guest
sends: memory the guest sees (available) and memory it could still use (usable, like MemAvailable).
Their difference is what the guest really uses, without its page cache. Host-side RSS is no use for
sizing: pages a VM has touched stay resident, so RSS only grows.

Balloon statistics refresh only while the VM's balloon has a statistics period set. Stale figures
(older than FRESH seconds) are skipped, so a VM is never sized from an old reading.
"""
import logging

import requests

log = logging.getLogger(__name__)
FRESH = 300
_FRESH = f"((time() - libvirt_domain_memory_stats_last_update_timestamp_seconds) < {FRESH})"
_JOIN = '* on (domain, vme_host) group_left (vm_id) vme_vm_info'


def _with_vm(expr):
    """Keep fresh readings and add the VME VM id (vme_vm_info maps libvirt domains to VMs)."""
    return (f'label_replace(({expr}) and on (domain, instance) {_FRESH}, "vme_host", "$1", "nodename", "(.*)") '
            f"{_JOIN}")


QUERIES = {
    "mem_guest_used_bytes": _with_vm("libvirt_domain_memory_stats_available_bytes"
                                     " - libvirt_domain_memory_stats_usable_bytes"),
    "mem_guest_swap_out_bps": _with_vm("rate(libvirt_domain_memory_stats_swap_out_bytes[5m])"),
}
_warned = set()


def points(cfg):
    """[('vm', vm_id, metric, value)] for VMs with fresh balloon statistics; [] without the exporters."""
    ex = cfg.get("exporters") or {}
    if not ex.get("enabled", True):
        return []
    url = (ex.get("prometheus_url") or "http://prometheus:9090").rstrip("/")
    out = []
    s = requests.Session()
    s.trust_env = False  # Prometheus is inside the stack: never through a proxy
    for metric, q in QUERIES.items():
        try:
            r = s.get(f"{url}/api/v1/query", params={"query": q}, timeout=10)
            r.raise_for_status()
            result = r.json()["data"]["result"]
        except (requests.RequestException, ValueError, KeyError) as e:
            if metric not in _warned:  # once, not every minute
                log.warning("guest memory from Prometheus unavailable (%s): %s", metric, e)
                _warned.add(metric)
            continue
        _warned.discard(metric)
        for row in result:
            try:
                vm_id, value = int(row["metric"]["vm_id"]), float(row["value"][1])
            except (KeyError, ValueError, TypeError):
                continue
            if value >= 0:
                out.append(("vm", vm_id, metric, value))
    return out
