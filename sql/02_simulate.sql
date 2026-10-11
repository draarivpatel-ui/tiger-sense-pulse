-- 02_simulate.sql
-- Seven days of readings, one every 5 minutes, for every sensor
-- (6 sensors x 2,017 timestamps = 12,102 rows).
-- Instead of pure random() noise, each sensor follows a daily sine curve
-- (warmest around 3 PM US Central time, i.e. 20:00 UTC) plus jitter, so the charts look like real data.
-- A few deliberate spikes are added so the anomaly query has something to find.

INSERT INTO sensor_data (time, sensor_id, temperature, humidity, cpu)
SELECT
  g.t,
  s.id,
  round((s.base_temp
         + s.swing * sin(2 * pi() * (extract(epoch FROM g.t) / 86400.0 - 0.583))
         + (random() - 0.5) * 0.8)::numeric, 2)::float8              AS temperature,
  round(greatest(5, least(100,
         60 - 15 * sin(2 * pi() * (extract(epoch FROM g.t) / 86400.0 - 0.583))
         + (random() - 0.5) * 10))::numeric, 1)::float8              AS humidity,
  round((CASE WHEN s.type = 'server' THEN 0.45 ELSE 0.15 END
         + random() * 0.25)::numeric, 3)::float8                     AS cpu
FROM generate_series(date_trunc('hour', now()) - interval '7 days',
                     date_trunc('hour', now()),
                     interval '5 minutes') AS g(t)
CROSS JOIN sensors s;

-- Inject anomalies: a greenhouse vent left shut and a server-room AC failure.
UPDATE sensor_data SET temperature = temperature + 9
WHERE sensor_id = (SELECT id FROM sensors WHERE name = 'greenhouse')
  AND time BETWEEN date_trunc('hour', now()) - interval '3 days 4 hours'
               AND date_trunc('hour', now()) - interval '3 days 2 hours';

UPDATE sensor_data SET temperature = temperature + 12, cpu = least(1, cpu + 0.4)
WHERE sensor_id = (SELECT id FROM sensors WHERE name = 'server-rm')
  AND time BETWEEN date_trunc('hour', now()) - interval '1 day 6 hours'
               AND date_trunc('hour', now()) - interval '1 day 5 hours';

ANALYZE sensor_data;
