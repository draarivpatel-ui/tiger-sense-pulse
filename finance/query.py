"""Show what landed in Tiger Cloud: hypertable, chunks, tick counts, the 1-minute OHLC candles and the refresh job.

Usage: DATABASE_URL=postgres://... python finance/query.py [--minutes 10]
"""
import argparse
import os

QUERIES = [
    ("Hypertable", "SELECT hypertable_name, num_dimensions, num_chunks, compression_enabled "
                   "FROM timescaledb_information.hypertables WHERE hypertable_name = 'crypto_ticks'"),
    ("Ticks per symbol", "SELECT symbol, count(*) AS ticks, min(time) AS first_tick, max(time) AS last_tick, "
                         "round(min(price), 2) AS min_price, round(max(price), 2) AS max_price "
                         "FROM crypto_ticks GROUP BY symbol ORDER BY symbol"),
    ("1-minute OHLC from the continuous aggregate crypto_ohlc_1m (last {minutes} min)",
     "SELECT bucket, symbol, round(open, 2) AS open, round(high, 2) AS high, round(low, 2) AS low, "
     "round(close, 2) AS close, ticks FROM crypto_ohlc_1m "
     "WHERE bucket > now() - make_interval(mins => %(minutes)s) ORDER BY symbol, bucket"),
    ("Background refresh policy on crypto_ohlc_1m",
     "SELECT j.job_id, j.schedule_interval, s.last_run_status, s.last_successful_finish, s.total_runs "
     "FROM timescaledb_information.jobs j JOIN timescaledb_information.job_stats s USING (job_id) "
     "WHERE j.proc_name = 'policy_refresh_continuous_aggregate' AND j.hypertable_name = 'crypto_ohlc_1m'"),
]


def fmt(v):
    if hasattr(v, "strftime"):
        return v.strftime("%Y-%m-%d %H:%M:%S") + ("+00" if v.utcoffset() is not None else "")
    return "" if v is None else str(v)


def table(cols, rows):
    cells = [[fmt(v) for v in r] for r in rows]
    w = [max([len(c)] + [len(r[i]) for r in cells]) for i, c in enumerate(cols)]
    out = [" " + " | ".join(c.center(w[i]) for i, c in enumerate(cols)), "-" + "-+-".join("-" * x for x in w) + "-"]
    out += [" " + " | ".join(r[i].ljust(w[i]) for i in range(len(cols))) for r in cells]
    out.append("(%d row%s)" % (len(rows), "" if len(rows) == 1 else "s"))
    return "\n".join(out)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--minutes", type=int, default=10)
    args = ap.parse_args()
    import psycopg
    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
        conn.execute("SET TIME ZONE 'UTC'")
        ver = conn.execute("SELECT extversion FROM pg_extension WHERE extname = 'timescaledb'").fetchone()[0]
        print("TimescaleDB %s on Tiger Cloud (times in UTC)" % ver)
        for title, sql in QUERIES:
            cur = conn.execute(sql, {"minutes": args.minutes})
            print("\n--- " + title.format(minutes=args.minutes))
            print(table([d.name for d in cur.description], cur.fetchall()))


if __name__ == "__main__":
    main()
