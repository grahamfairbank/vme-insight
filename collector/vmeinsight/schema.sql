-- vme-insight schema. Applied by the collector at every start; every block is idempotent.
-- Blocks are separated by "-- @@" lines and run one at a time in autocommit
-- (continuous aggregates cannot be created inside a transaction).

CREATE EXTENSION IF NOT EXISTS timescaledb;
-- @@

-- ---------------------------------------------------------------- time series
-- Narrow table: one row per (time, entity, metric). New metrics need no schema change.
CREATE TABLE IF NOT EXISTS metrics (
  time        timestamptz      NOT NULL,
  entity_type text             NOT NULL,   -- host | vm | cluster | datastore | appliance | summary
  entity_id   bigint           NOT NULL,
  metric      text             NOT NULL,
  value       double precision NOT NULL
);
-- @@
SELECT create_hypertable('metrics', 'time', chunk_time_interval => INTERVAL '1 day', if_not_exists => TRUE);
-- @@
CREATE INDEX IF NOT EXISTS metrics_lookup ON metrics (entity_type, metric, entity_id, time DESC);
-- @@
DO $$ BEGIN
  IF NOT EXISTS (SELECT 1 FROM timescaledb_information.hypertables
                 WHERE hypertable_name = 'metrics' AND compression_enabled) THEN
    ALTER TABLE metrics SET (timescaledb.compress,
      timescaledb.compress_segmentby = 'entity_type, entity_id, metric',
      timescaledb.compress_orderby   = 'time DESC');
  END IF;
END $$;
-- @@
CREATE MATERIALIZED VIEW IF NOT EXISTS metrics_hourly WITH (timescaledb.continuous) AS
SELECT time_bucket(INTERVAL '1 hour', time) AS bucket,
       entity_type, entity_id, metric,
       avg(value) AS avg, min(value) AS min, max(value) AS max, count(*) AS samples
FROM metrics
GROUP BY 1, 2, 3, 4
WITH NO DATA;
-- @@
SELECT add_continuous_aggregate_policy('metrics_hourly',
  start_offset => INTERVAL '3 days', end_offset => INTERVAL '1 hour',
  schedule_interval => INTERVAL '30 minutes', if_not_exists => TRUE);
-- @@

-- ---------------------------------------------------------------- inventory
CREATE TABLE IF NOT EXISTS appliance (
  id            int PRIMARY KEY DEFAULT 1,
  url           text,
  build_version text,
  last_seen     timestamptz NOT NULL DEFAULT now(),
  raw           jsonb
);
-- @@
CREATE TABLE IF NOT EXISTS clouds (
  id bigint PRIMARY KEY, name text, type_code text, type_name text, status text,
  present bool NOT NULL DEFAULT true,
  first_seen timestamptz NOT NULL DEFAULT now(), last_seen timestamptz NOT NULL DEFAULT now(),
  raw jsonb
);
-- @@
CREATE TABLE IF NOT EXISTS clusters (
  id bigint PRIMARY KEY, name text, type_code text, type_name text, cloud_id bigint, status text,
  host_ids bigint[],
  present bool NOT NULL DEFAULT true,
  first_seen timestamptz NOT NULL DEFAULT now(), last_seen timestamptz NOT NULL DEFAULT now(),
  raw jsonb
);
-- @@
-- Hypervisor hosts and virtual machines are both "servers" in the Morpheus API.
CREATE TABLE IF NOT EXISTS servers (
  id bigint PRIMARY KEY,
  kind text NOT NULL,                 -- host | vm
  name text, hostname text,
  cloud_id bigint, cluster_id bigint, host_id bigint,
  type_code text, type_name text, managed bool,
  status text, power_state text,
  ip_internal text, ip_external text,
  os_name text, os_type text, platform text, platform_version text,
  os_product text, os_cycle text, os_version_full text,  -- normalised for lifecycle lookups
  agent_installed bool, agent_version text, agent_last_update timestamptz,
  max_cores int, max_memory bigint, max_storage bigint,
  date_created timestamptz,
  present bool NOT NULL DEFAULT true,
  first_seen timestamptz NOT NULL DEFAULT now(), last_seen timestamptz NOT NULL DEFAULT now(),
  raw jsonb
);
-- @@
CREATE INDEX IF NOT EXISTS servers_kind ON servers (kind, present);
-- @@
CREATE TABLE IF NOT EXISTS instances (
  id bigint PRIMARY KEY, name text, instance_type text, layout text, plan text,
  status text, power_state text, cloud_id bigint, owner text, created_by text,
  environment text, tags text, server_ids bigint[], date_created timestamptz,
  present bool NOT NULL DEFAULT true,
  first_seen timestamptz NOT NULL DEFAULT now(), last_seen timestamptz NOT NULL DEFAULT now(),
  raw jsonb
);
-- @@
CREATE TABLE IF NOT EXISTS datastores (
  id bigint PRIMARY KEY, name text, type text, cloud_id bigint, cluster_id bigint,
  active bool, status text, capacity_bytes bigint, free_bytes bigint,
  present bool NOT NULL DEFAULT true,
  first_seen timestamptz NOT NULL DEFAULT now(), last_seen timestamptz NOT NULL DEFAULT now(),
  raw jsonb
);
-- @@
CREATE TABLE IF NOT EXISTS networks (
  id bigint PRIMARY KEY, name text, type text, cloud_id bigint, cidr text, vlan_id int,
  dhcp bool, status text,
  present bool NOT NULL DEFAULT true,
  first_seen timestamptz NOT NULL DEFAULT now(), last_seen timestamptz NOT NULL DEFAULT now(),
  raw jsonb
);
-- @@
CREATE TABLE IF NOT EXISTS alarms (
  id bigint PRIMARY KEY, name text, event_key text, status text, severity text,
  resource_name text, ref_type text, ref_id bigint, message text,
  acknowledged bool, active bool NOT NULL DEFAULT true,
  start_date timestamptz,
  present bool NOT NULL DEFAULT true,
  first_seen timestamptz NOT NULL DEFAULT now(), last_seen timestamptz NOT NULL DEFAULT now(),
  raw jsonb
);
-- @@

ALTER TABLE appliance ADD COLUMN IF NOT EXISTS health jsonb;
-- @@
ALTER TABLE appliance ADD COLUMN IF NOT EXISTS health_at timestamptz;
-- @@
ALTER TABLE clouds ADD COLUMN IF NOT EXISTS last_sync timestamptz;
-- @@
CREATE TABLE IF NOT EXISTS activity (
  key text PRIMARY KEY, ts timestamptz NOT NULL, name text, activity_type text, object_type text,
  message text, user_name text, success bool, raw jsonb
);
-- @@
ALTER TABLE clusters ADD COLUMN IF NOT EXISTS layout text;
-- @@
ALTER TABLE servers
  ADD COLUMN IF NOT EXISTS guest_agent_status text, ADD COLUMN IF NOT EXISTS maintenance bool,
  ADD COLUMN IF NOT EXISTS member_status text, ADD COLUMN IF NOT EXISTS hw_vendor text,
  ADD COLUMN IF NOT EXISTS hw_model text, ADD COLUMN IF NOT EXISTS cpu_model text,
  ADD COLUMN IF NOT EXISTS cpu_sockets int, ADD COLUMN IF NOT EXISTS plan text,
  ADD COLUMN IF NOT EXISTS source_image text;
-- @@
CREATE INDEX IF NOT EXISTS activity_ts ON activity (ts DESC);
-- @@

-- ---------------------------------------------------------------- change tracking
CREATE TABLE IF NOT EXISTS inventory_changes (
  time timestamptz NOT NULL DEFAULT now(),
  entity_type text NOT NULL, entity_id bigint NOT NULL, name text,
  field text NOT NULL, old_value text, new_value text
);
-- @@
CREATE INDEX IF NOT EXISTS inventory_changes_time ON inventory_changes (time DESC);
-- @@
CREATE OR REPLACE FUNCTION track_server_changes() RETURNS trigger LANGUAGE plpgsql AS $$
DECLARE f text; o text; n text;
BEGIN
  IF TG_OP = 'INSERT' THEN
    INSERT INTO inventory_changes (entity_type, entity_id, name, field, new_value)
    VALUES (NEW.kind, NEW.id, NEW.name, 'discovered', NEW.name);
    RETURN NEW;
  END IF;
  FOREACH f IN ARRAY ARRAY['name','present','status','power_state','os_name','platform_version',
      'os_version_full','agent_installed','agent_version','max_cores','max_memory','max_storage',
      'host_id','cluster_id','ip_internal','guest_agent_status','maintenance','member_status'] LOOP
    EXECUTE format('SELECT ($1).%1$I::text, ($2).%1$I::text', f) INTO o, n USING OLD, NEW;
    IF o IS DISTINCT FROM n THEN
      INSERT INTO inventory_changes (entity_type, entity_id, name, field, old_value, new_value)
      VALUES (NEW.kind, NEW.id, NEW.name, f, o, n);
    END IF;
  END LOOP;
  RETURN NEW;
END $$;
-- @@
CREATE OR REPLACE TRIGGER servers_changes AFTER INSERT OR UPDATE ON servers
  FOR EACH ROW EXECUTE FUNCTION track_server_changes();
-- @@

-- ---------------------------------------------------------------- lifecycle / currency
CREATE TABLE IF NOT EXISTS os_lifecycle (
  product text NOT NULL, cycle text NOT NULL,
  release_date date, eol_date date, eol_bool bool, support_date date, lts bool,
  latest text, latest_date date,
  fetched_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (product, cycle)
);
-- @@
CREATE TABLE IF NOT EXISTS settings (key text PRIMARY KEY, value text);
-- @@
CREATE TABLE IF NOT EXISTS collector_runs (
  time timestamptz NOT NULL DEFAULT now(), task text NOT NULL, ok bool NOT NULL,
  duration_ms int, items int, error text
);
-- @@
CREATE INDEX IF NOT EXISTS collector_runs_time ON collector_runs (time DESC);
-- @@
-- "9.4.1-2" -> {9,4,1,2}; arrays compare element-wise, so this orders versions.
CREATE OR REPLACE FUNCTION version_key(v text) RETURNS bigint[] LANGUAGE sql IMMUTABLE AS $$
  SELECT CASE WHEN v IS NULL OR v !~ '\d' THEN NULL
         ELSE ARRAY(SELECT (m[1])::bigint FROM regexp_matches(v, '(\d{1,15})', 'g') AS m) END
$$;
-- @@
CREATE OR REPLACE VIEW agent_target AS
SELECT COALESCE(
  NULLIF((SELECT value FROM settings WHERE key = 'expected_agent_version'), ''),
  (SELECT agent_version FROM servers
    WHERE present AND agent_version IS NOT NULL AND agent_version ~ '\d'
    ORDER BY version_key(agent_version) DESC LIMIT 1)) AS version;
-- @@
CREATE OR REPLACE VIEW server_currency AS
SELECT s.id, s.kind, s.name, s.power_state, s.status, s.cluster_id,
       cl.name AS cluster, h.name AS host, cd.name AS cloud,
       s.os_name, s.os_product, s.os_cycle, s.os_version_full,
       l.release_date AS os_release_date, l.eol_date, l.support_date, l.latest AS os_latest,
       (l.eol_date - current_date) AS days_to_eol,
       CASE WHEN s.os_product IS NULL THEN 'unknown os'
            WHEN l.cycle IS NULL THEN 'unknown release'
            WHEN l.eol_date <= current_date OR (l.eol_date IS NULL AND l.eol_bool) THEN 'end of life'
            WHEN l.eol_date <= current_date + 180 THEN 'eol < 180d'
            -- only when the reported version is more precise than the cycle ("22.04.3", not "22.04")
            WHEN s.os_version_full IS NOT NULL AND l.latest IS NOT NULL
                 AND cardinality(version_key(s.os_version_full)) > cardinality(version_key(l.cycle))
                 AND version_key(s.os_version_full) < version_key(l.latest) THEN 'update available'
            ELSE 'current' END AS os_status,
       s.agent_installed, s.agent_version, t.version AS agent_target,
       CASE WHEN NOT COALESCE(s.agent_installed, false) THEN 'not installed'
            WHEN s.agent_version IS NULL THEN 'unknown'
            WHEN version_key(s.agent_version) < version_key(t.version) THEN 'outdated'
            ELSE 'current' END AS agent_status,
       s.agent_last_update,
       EXTRACT(epoch FROM now() - s.agent_last_update)::bigint AS agent_age_s,
       s.max_cores, s.max_memory, s.max_storage, s.ip_internal, s.first_seen, s.last_seen,
       s.guest_agent_status, s.hw_model, s.cpu_model
FROM servers s
CROSS JOIN agent_target t
LEFT JOIN clusters cl ON cl.id = s.cluster_id
LEFT JOIN servers  h  ON h.id  = s.host_id
LEFT JOIN clouds   cd ON cd.id = s.cloud_id
LEFT JOIN os_lifecycle l ON l.product = s.os_product AND lower(l.cycle) = lower(s.os_cycle)
WHERE s.present;
