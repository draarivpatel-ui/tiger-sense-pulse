-- finance/schema.sql
-- Real-time crypto prices on Tiger Cloud: a tick hypertable + a 1-minute OHLC continuous aggregate.
-- Safe to re-run: only touches crypto_ticks and crypto_ohlc_1m, and only creates what is missing.

-- One row per price update the feed publishes. `time` is the feed's own
-- last_updated_at, so polling the same update twice is a no-op (primary key).
CREATE TABLE IF NOT EXISTS crypto_ticks (
  time           TIMESTAMPTZ NOT NULL,           -- when CoinGecko last updated this price
  symbol         TEXT        NOT NULL,           -- 'BTC-USD', 'ETH-USD', 'SOL-USD'
  price          NUMERIC     NOT NULL,           -- USD
  volume_24h_usd NUMERIC,                        -- rolling 24 h volume as reported with this price
  fetched_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
  source         TEXT        NOT NULL DEFAULT 'coingecko',
  PRIMARY KEY (symbol, time)
) WITH (
  tsdb.hypertable,
  tsdb.partition_column = 'time',
  tsdb.segmentby = 'symbol',
  tsdb.orderby   = 'time DESC',
  tsdb.chunk_interval = '1 day'
);

-- 1-minute OHLC candles, kept up to date in the background.
-- materialized_only = false makes it a real-time aggregate: the newest,
-- not-yet-materialized minute is computed from crypto_ticks on the fly.
CREATE MATERIALIZED VIEW IF NOT EXISTS crypto_ohlc_1m
WITH (timescaledb.continuous, timescaledb.materialized_only = false) AS
SELECT
  time_bucket('1 minute', time) AS bucket,
  symbol,
  first(price, time)            AS open,
  max(price)                    AS high,
  min(price)                    AS low,
  last(price, time)             AS close,
  last(volume_24h_usd, time)    AS volume_24h_usd,
  count(*)                      AS ticks
FROM crypto_ticks
GROUP BY bucket, symbol
WITH NO DATA;

-- Every minute, re-materialize the last hour (up to one minute ago).
SELECT add_continuous_aggregate_policy('crypto_ohlc_1m',
  start_offset      => INTERVAL '1 hour',
  end_offset        => INTERVAL '1 minute',
  schedule_interval => INTERVAL '1 minute',
  if_not_exists     => true);
