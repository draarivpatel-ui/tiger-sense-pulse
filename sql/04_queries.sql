-- 04_queries.sql  ·  queries you can run in the Tiger Console SQL editor.

\echo '--- 1. Hypertable health: chunks and row count'
SELECT hypertable_name, num_chunks
FROM timescaledb_information.hypertables WHERE hypertable_name = 'sensor_data';
SELECT count(*) AS raw_rows FROM sensor_data;

\echo '--- 2. Latest reading per sensor (joins time-series with metadata)'
SELECT DISTINCT ON (s.name)
  s.name, s.location, d.time, d.temperature, d.humidity
FROM sensor_data d JOIN sensors s ON s.id = d.sensor_id
ORDER BY s.name, d.time DESC;

\echo '--- 3. 30-minute averages with last() for one sensor, last 3 hours'
SELECT time_bucket('30 minutes', time) AS period,
       round(avg(temperature)::numeric, 2)       AS avg_temp,
       round(last(temperature, time)::numeric, 2) AS last_temp,
       round(avg(cpu)::numeric, 3)               AS avg_cpu
FROM sensor_data
WHERE sensor_id = (SELECT id FROM sensors WHERE name = 'greenhouse')
  AND time > now() - interval '3 hours'
GROUP BY period ORDER BY period;

\echo '--- 4. Daily summary from the hierarchical continuous aggregate'
SELECT d.day::date, s.name,
       round(d.avg_temp::numeric, 1) AS avg_c,
       round(d.min_temp::numeric, 1) AS min_c,
       round(d.max_temp::numeric, 1) AS max_c
FROM sensor_daily d JOIN sensors s ON s.id = d.sensor_id
WHERE s.name IN ('greenhouse', 'server-rm')
ORDER BY s.name, d.day;

\echo '--- 5. Anomaly finder: hours running > 4 C above that sensor''s typical (median) for the same hour of day'
WITH typical AS (
  SELECT sensor_id, extract(hour FROM bucket) AS hr,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY avg_temp) AS median_temp
  FROM sensor_hourly GROUP BY sensor_id, hr
)
SELECT s.name, h.bucket, round(h.max_temp::numeric, 1) AS max_temp,
       round((h.avg_temp - t.median_temp)::numeric, 1) AS above_typical
FROM sensor_hourly h
JOIN typical t ON t.sensor_id = h.sensor_id AND t.hr = extract(hour FROM h.bucket)
JOIN sensors s ON s.id = h.sensor_id
WHERE h.avg_temp - t.median_temp > 4
ORDER BY h.bucket;

\echo '--- 6. Speed check: raw table vs continuous aggregate for the same question'
EXPLAIN (ANALYZE, COSTS OFF, TIMING ON, SUMMARY ON)
SELECT time_bucket('1 hour', time) AS bucket, sensor_id, avg(temperature)
FROM sensor_data GROUP BY 1, 2;
EXPLAIN (ANALYZE, COSTS OFF, TIMING ON, SUMMARY ON)
SELECT bucket, sensor_id, avg_temp FROM sensor_hourly;

\echo '--- 7. Background jobs that keep the CAGGs fresh'
SELECT job_id, proc_name, schedule_interval, hypertable_name
FROM timescaledb_information.jobs WHERE proc_name = 'policy_refresh_continuous_aggregate';
