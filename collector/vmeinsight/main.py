"""Collector entry point: runs each task on its own interval forever."""
import logging
import os
import signal
import time
from pathlib import Path

from . import config, infoexport, lifecycle
from .collect import Collector
from .db import DB
from .morpheus import Morpheus

log = logging.getLogger("vmeinsight")
HEARTBEAT = Path(os.environ.get("HEARTBEAT_FILE", "/tmp/heartbeat"))
_stop = False


def _sigterm(*_):
    global _stop
    _stop = True


def main():
    cfg = config.load()
    logging.basicConfig(level=cfg.get("log_level", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    signal.signal(signal.SIGTERM, _sigterm)
    signal.signal(signal.SIGINT, _sigterm)

    db = DB(os.environ["DATABASE_URL"])
    db.connect()
    db.migrate(cfg["retention"], os.environ.get("GRAFANA_DB_PASSWORD"))
    api = Morpheus(cfg["morpheus"])
    col = Collector(api, db, cfg)
    infoexport.serve()

    # order matters on the first pass: inventory and clusters before storage
    tasks = [
        ("inventory", col.inventory),
        ("metrics", col.metrics),
        ("storage", col.storage),
        ("health", col.health),
        ("lifecycle", lambda: lifecycle.refresh(db, cfg)),
    ]
    intervals = cfg["intervals"]
    due = {name: 0.0 for name, _ in tasks}
    log.info("collecting from %s", api.base)

    while not _stop:
        for name, fn in tasks:
            if _stop or time.time() < due[name]:
                continue
            started = time.time()
            try:
                n = fn()
                ms = int((time.time() - started) * 1000)
                db.log_run(name, True, ms, n)
                log.info("%s: %s items in %d ms", name, n, ms)
                due[name] = started + int(intervals[name])
                if name in ("metrics", "storage"):
                    infoexport.refresh(db)
            except Exception as e:  # keep going; retry sooner than the full interval
                ms = int((time.time() - started) * 1000)
                log.exception("%s failed", name)
                db.log_run(name, False, ms, error=f"{type(e).__name__}: {e}")
                due[name] = started + min(int(intervals[name]), 120)
        HEARTBEAT.touch()
        time.sleep(1)
    log.info("stopped")


if __name__ == "__main__":
    main()
