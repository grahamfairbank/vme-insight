"""Tiny Prometheus endpoint with VME inventory labels, so exporter series can be joined
to VME names (e.g. a host's /mnt/<uuid> mount -> datastore "silo").

Served on :9105/metrics inside the compose network; Prometheus scrapes it as job vme-info.
"""
import logging
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

log = logging.getLogger(__name__)
_text = "# no data yet\n"
_lock = threading.Lock()


def _esc(v):
    return str(v if v is not None else "").replace("\\", "\\\\").replace('"', '\\"').replace("\n", " ")


def _series(name, labels):
    return name + "{" + ",".join(f'{k}="{_esc(v)}"' for k, v in labels.items()) + "} 1"


def refresh(db):
    """Rebuild the exposition text from the inventory tables."""
    global _text
    lines = [
        "# HELP vme_datastore_info VME datastore mounted on HVM hosts at this path.",
        "# TYPE vme_datastore_info gauge",
    ]
    for ds_id, name, dtype, path in db.execute(
            "SELECT id, name, type, raw->>'externalPath' FROM datastores "
            "WHERE present AND raw->>'externalPath' LIKE '/%'") or []:
        lines.append(_series("vme_datastore_info", {
            "mountpoint": path, "datastore": name, "datastore_type": dtype, "datastore_id": ds_id}))
    lines += ["# HELP vme_vm_info VME virtual machine for a libvirt domain.", "# TYPE vme_vm_info gauge"]
    for vm_id, name, domain, host in db.execute(
            "SELECT s.id, s.name, COALESCE(s.raw->>'externalId', s.name), h.name FROM servers s "
            "LEFT JOIN servers h ON h.id = s.host_id WHERE s.kind = 'vm' AND s.present") or []:
        lines.append(_series("vme_vm_info", {"domain": domain, "vm": name, "vm_id": vm_id, "vme_host": host}))
    with _lock:
        _text = "\n".join(lines) + "\n"


class _Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.split("?")[0] != "/metrics":
            self.send_error(404)
            return
        with _lock:
            body = _text.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # keep the collector log quiet
        pass


def serve(port=9105):
    srv = ThreadingHTTPServer(("0.0.0.0", port), _Handler)
    threading.Thread(target=srv.serve_forever, daemon=True, name="info-export").start()
    log.info("inventory labels for Prometheus on :%d/metrics", port)
