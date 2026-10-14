"""Poll the keyless CoinGecko price feed and write ticks into the crypto_ticks hypertable on Tiger Cloud.

Usage:
  pip install "psycopg[binary]"
  export DATABASE_URL="postgres://tsdbadmin:<password>@<host>:<port>/tsdb?sslmode=require"
  python finance/ingest.py --setup --seconds 300          # create schema, then ingest for 5 minutes
  python finance/ingest.py --seconds 0                     # run until Ctrl-C
Data provided by CoinGecko (https://www.coingecko.com/en/api).
"""
import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import feed  # noqa: E402

INSERT = ("INSERT INTO crypto_ticks (time, symbol, price, volume_24h_usd) VALUES (%s, %s, %s, %s) "
          "ON CONFLICT (symbol, time) DO NOTHING")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seconds", type=float, default=300, help="how long to run (0 = until Ctrl-C)")
    ap.add_argument("--interval", type=float, default=feed.DEFAULT_INTERVAL_S, help="seconds between requests (min 1)")
    ap.add_argument("--setup", action="store_true", help="apply finance/schema.sql first")
    args = ap.parse_args(argv)

    import psycopg  # imported here so the parsing module and tests need no database driver

    interval = feed.clamp_interval(args.interval)
    url = feed.build_url(list(feed.COINS))
    conn = psycopg.connect(os.environ["DATABASE_URL"], autocommit=True)
    if args.setup:
        conn.execute((HERE / "schema.sql").read_text())
        print("schema ready: crypto_ticks (hypertable) + crypto_ohlc_1m (continuous aggregate)", flush=True)

    # Resume where an earlier run stopped, so restarts never re-count stored updates.
    last_seen = dict(conn.execute("SELECT symbol, max(time) FROM crypto_ticks GROUP BY symbol").fetchall())
    # Last good prices to show (never re-insert) if the feed answers 403 or 429 before the first live poll.
    last_good = {sym: {"time": t, "symbol": sym, "price": p, "volume_24h_usd": v} for sym, t, p, v in conn.execute(
        "SELECT DISTINCT ON (symbol) symbol, time, price, volume_24h_usd FROM crypto_ticks "
        "ORDER BY symbol, time DESC").fetchall()}
    inserted, polls, failed = 0, 0, 0
    deadline = None if args.seconds <= 0 else time.monotonic() + args.seconds
    try:
        while deadline is None or time.monotonic() < deadline:
            started = time.monotonic()
            now = datetime.now(timezone.utc).strftime("%H:%M:%S")
            wait = interval
            result = feed.poll(url, last_good)
            prices = "  ".join("%s %s" % (t["symbol"].split("-")[0], f"{t['price']:,.2f}") for t in result.ticks)
            if result.live:
                polls += 1
                failed = 0
                fresh = feed.new_ticks(result.ticks, last_seen)
                written = 0
                with conn.cursor() as cur:
                    for t in fresh:
                        cur.execute(INSERT, (t["time"], t["symbol"], t["price"], t["volume_24h_usd"]))
                        written += cur.rowcount  # 0 when the row was already stored
                inserted += written
                print(f"{now} UTC  poll {polls:>2}  {prices}  new={written}", flush=True)
            else:
                # 403 blocked or 429 rate limited: nothing is written; show the cached prices and back off.
                failed += 1
                wait = feed.backoff_seconds(failed, interval)
                print(f"{now} UTC  {result.note}; backing off {wait:.0f}s" + (f"  [{prices}]" if prices else ""),
                      flush=True)
            sleep_for = wait - (time.monotonic() - started)
            if deadline is not None:
                sleep_for = min(sleep_for, deadline - time.monotonic())
            if sleep_for > 0:
                time.sleep(sleep_for)
    except KeyboardInterrupt:
        pass
    finally:
        conn.close()
    print(f"done: {polls} successful polls, {inserted} new ticks written to crypto_ticks", flush=True)


if __name__ == "__main__":
    main()
