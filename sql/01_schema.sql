-- 01_schema.sql
-- Sensor metadata (a normal Postgres table) + readings (a TimescaleDB hypertable).
-- Safe to re-run: drops the demo objects first.

DROP MATERIALIZED VIEW IF EXISTS sensor_daily CASCADE;
DROP MATERIALIZED VIEW IF EXISTS sensor_hourly CASCADE;
DROP TABLE IF EXISTS sensor_data CASCADE;
DROP TABLE IF EXISTS sensors CASCADE;

CREATE TABLE sensors (
  id        SERIAL PRIMARY KEY,
  name      TEXT NOT NULL UNIQUE,
  type      TEXT NOT NULL,          -- 'indoor' | 'outdoor' | 'server'
  location  TEXT NOT NULL,
  -- baseline used only by the simulator, so each sensor looks different
  base_temp DOUBLE PRECISION NOT NULL,
  swing     DOUBLE PRECISION NOT NULL
);

-- `WITH (tsdb.hypertable ...)` turns the table into a hypertable, partitioned
-- by the first TIMESTAMPTZ column (time) into chunks. segmentby/orderby tune
-- how rows are grouped when chunks move to the columnstore.
CREATE TABLE sensor_data (
  time        TIMESTAMPTZ      NOT NULL,
  sensor_id   INTEGER          NOT NULL REFERENCES sensors (id),
  temperature DOUBLE PRECISION,     -- degrees C
  humidity    DOUBLE PRECISION,     -- percent
  cpu         DOUBLE PRECISION      -- 0..1 load on the sensor's microcontroller
) WITH (
  tsdb.hypertable,
  tsdb.segmentby = 'sensor_id',
  tsdb.orderby   = 'time DESC',
  tsdb.chunk_interval = '1 day'
);

-- Most queries ask "this sensor, this time range".
CREATE INDEX ON sensor_data (sensor_id, time DESC);

INSERT INTO sensors (name, type, location, base_temp, swing) VALUES
  ('lab-1',      'indoor',  'Robotics lab',        22.0, 1.5),
  ('lab-2',      'indoor',  'Chemistry lab',       21.0, 2.0),
  ('library',    'indoor',  'Library study room',  23.0, 1.0),
  ('greenhouse', 'indoor',  'Science greenhouse',  27.0, 6.0),
  ('courtyard',  'outdoor', 'Front courtyard',     26.0, 7.0),
  ('server-rm',  'server',  'Server closet',       24.0, 2.5);
