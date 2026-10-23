"""Database access: migrations, upserts, metric writes."""
import logging
import time
from pathlib import Path

import psycopg
from psycopg import sql

log = logging.getLogger(__name__)
SCHEMA = Path(__file__).with_name("schema.sql")


DB_PASSWORD_HELP = (
    "The database rejected DB_PASSWORD from .env. TimescaleDB keeps the password it was first created with, "
    "and its data volume survives reinstalls and fresh clones (the project is always named vme-insight). "
    "Fix one of three ways: put the original password back in .env; or keep the data and set the new one: "
    "docker compose exec timescaledb psql -U vme -d vme -c \"ALTER ROLE vme PASSWORD '<DB_PASSWORD>'\" "
    "&& docker compose restart collector; or start clean, DELETING all collected data: "
    "docker compose --profile https --profile installer down -v && docker compose up -d. "
    "See docs/TROUBLESHOOTING.md#collector-wont-start")


class DB:
    def __init__(self, dsn):
        self.dsn = dsn
        self.conn = None

    def connect(self, wait=120):
        deadline = time.time() + wait
        while True:
            try:
                self.conn = psycopg.connect(self.dsn, autocommit=True)
                return
            except psycopg.OperationalError as e:
                if "password authentication failed" in str(e):
                    # waiting won't help: the database volume keeps the password it was created with
                    log.error(DB_PASSWORD_HELP)
                    raise SystemExit(1)
                if time.time() > deadline:
                    raise
                log.info("waiting for database: %s", str(e).strip().splitlines()[0])
                time.sleep(3)

    def ensure(self):
        if self.conn is None or self.conn.closed or self.conn.broken:
            self.connect()

    def execute(self, q, params=None):
        self.ensure()
        with self.conn.cursor() as cur:
            cur.execute(q, params)
            return cur.fetchall() if cur.description else None

    # -- schema ---------------------------------------------------------
    def migrate(self, retention, grafana_password=None):
        self.ensure()
        for block in SCHEMA.read_text().split("\n-- @@\n"):
            if block.strip():
                self.conn.execute(block)
        r = retention
        for stmt in (
            "SELECT remove_retention_policy('metrics', if_exists => true)",
            f"SELECT add_retention_policy('metrics', INTERVAL '{int(r['raw'])} days')",
            "SELECT remove_retention_policy('metrics_hourly', if_exists => true)",
            f"SELECT add_retention_policy('metrics_hourly', INTERVAL '{int(r['hourly'])} days')",
            "SELECT remove_compression_policy('metrics', if_exists => true)",
            f"SELECT add_compression_policy('metrics', INTERVAL '{int(r['compress_after'])} days')",
        ):
            self.conn.execute(stmt)
        if grafana_password:
            self._grafana_role(grafana_password)
        log.info("schema ready (raw %sd, hourly %sd)", r["raw"], r["hourly"])

    def _grafana_role(self, password):
        exists = self.execute("SELECT 1 FROM pg_roles WHERE rolname = 'grafana_ro'")
        verb = "ALTER" if exists else "CREATE"
        self.conn.execute(sql.SQL(verb + " ROLE grafana_ro LOGIN PASSWORD {}").format(sql.Literal(password)))
        self.conn.execute("GRANT USAGE ON SCHEMA public TO grafana_ro")
        self.conn.execute("GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_ro")
        self.conn.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO grafana_ro")

    # -- writes ---------------------------------------------------------
    def upsert(self, table, rows, key="id"):
        """Insert-or-update rows (dicts with identical keys); marks them present."""
        if not rows:
            return
        cols = list(rows[0].keys())
        q = sql.SQL(
            "INSERT INTO {t} ({c}) VALUES ({v}) ON CONFLICT ({k}) DO UPDATE SET {u}, "
            "present = true, last_seen = now()"
        ).format(
            t=sql.Identifier(table),
            c=sql.SQL(", ").join(map(sql.Identifier, cols)),
            v=sql.SQL(", ").join(sql.Placeholder(c) for c in cols),
            k=sql.Identifier(key),
            u=sql.SQL(", ").join(
                sql.SQL("{0} = EXCLUDED.{0}").format(sql.Identifier(c)) for c in cols if c != key
            ),
        )
        self.ensure()
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.executemany(q, rows)

    def insert_ignore(self, table, rows, key):
        cols = list(rows[0].keys())
        q = sql.SQL("INSERT INTO {t} ({c}) VALUES ({v}) ON CONFLICT ({k}) DO NOTHING").format(
            t=sql.Identifier(table), c=sql.SQL(", ").join(map(sql.Identifier, cols)),
            v=sql.SQL(", ").join(sql.Placeholder(c) for c in cols), k=sql.Identifier(key))
        self.ensure()
        with self.conn.transaction(), self.conn.cursor() as cur:
            cur.executemany(q, rows)

    def mark_absent(self, table, seen_ids):
        """Flag rows not returned by a complete sweep as no longer present."""
        self.execute(
            sql.SQL("UPDATE {} SET present = false WHERE present AND NOT (id = ANY(%s))").format(
                sql.Identifier(table)),
            (list(seen_ids),),
        )

    def write_metrics(self, ts, points):
        """points: iterable of (entity_type, entity_id, metric, value)."""
        points = [(ts, et, int(eid), m, float(v)) for et, eid, m, v in points]
        if not points:
            return 0
        self.ensure()
        with self.conn.cursor() as cur:
            with cur.copy("COPY metrics (time, entity_type, entity_id, metric, value) FROM STDIN") as cp:
                for p in points:
                    cp.write_row(p)
        return len(points)

    def set_setting(self, key, value):
        self.execute(
            "INSERT INTO settings (key, value) VALUES (%s, %s) "
            "ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value",
            (key, value),
        )

    def log_run(self, task, ok, duration_ms, items=None, error=None):
        try:
            self.execute(
                "INSERT INTO collector_runs (task, ok, duration_ms, items, error) VALUES (%s,%s,%s,%s,%s)",
                (task, ok, duration_ms, items, (error or "")[:2000] or None),
            )
            self.execute("DELETE FROM collector_runs WHERE time < now() - INTERVAL '30 days'")
        except Exception:  # never let bookkeeping kill a task
            log.exception("could not record collector run")
