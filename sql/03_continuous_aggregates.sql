-- 03_continuous_aggregates.sql
-- Continuous aggregates (CAGGs) pre-compute rollups in the background so a
-- dashboard reads ~170 hourly rows per sensor instead of ~2,000 raw ones.

CREATE MATERIALIZED VIEW sensor_hourly
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 hour', time) AS bucket,
  sensor_id,
  avg(temperature)            AS avg_temp,
  min(temperature)            AS min_temp,
  max(temperature)            AS max_temp,
  avg(humidity)               AS avg_humidity,
  max(cpu)                    AS max_cpu,
  count(*)                    AS readings
FROM sensor_data
GROUP BY bucket, sensor_id
WITH NO DATA;

-- Keep it fresh automatically: every 30 minutes, re-materialize the window
-- from 3 days ago up to 1 hour ago (late-arriving data inside that window is picked up).
SELECT add_continuous_aggregate_policy('sensor_hourly',
  start_offset      => INTERVAL '3 days',
  end_offset        => INTERVAL '1 hour',
  schedule_interval => INTERVAL '30 minutes');

-- Hierarchical CAGG: a daily rollup built on top of the hourly one.
CREATE MATERIALIZED VIEW sensor_daily
WITH (timescaledb.continuous) AS
SELECT
  time_bucket('1 day', bucket) AS day,
  sensor_id,
  avg(avg_temp)                AS avg_temp,
  min(min_temp)                AS min_temp,
  max(max_temp)                AS max_temp,
  sum(readings)                AS readings
FROM sensor_hourly
GROUP BY day, sensor_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('sensor_daily',
  start_offset      => INTERVAL '7 days',
  end_offset        => INTERVAL '1 day',
  schedule_interval => INTERVAL '1 hour');

-- Back-fill the history we just simulated (policies only handle new windows).
CALL refresh_continuous_aggregate('sensor_hourly', NULL, NULL);
CALL refresh_continuous_aggregate('sensor_daily',  NULL, NULL);
