"""finance/: parsing, de-duplication and pacing of the keyless CoinGecko feed, plus the schema file (no network, no database)."""
import json
import sys
import unittest
from datetime import datetime, timezone
from decimal import Decimal

from sqlutil import ROOT, norm, read, statements, strip_sql

sys.path.insert(0, str(ROOT / "finance"))
import feed  # noqa: E402

# Shape of a real /simple/price response (values from an Oct 13, 2026 call).
SAMPLE = {
    "bitcoin": {"usd": 83380.23728352188, "usd_24h_vol": 32780789488.952454, "last_updated_at": 1791929184},
    "ethereum": {"usd": 2508.170533204109, "usd_24h_vol": 13977414413.098953, "last_updated_at": 1791929184},
    "solana": {"usd": 106.89363661156929, "usd_24h_vol": 3976912774.1616387, "last_updated_at": 1791929184},
}


class ParseSimplePrice(unittest.TestCase):
    def test_parses_all_three_coins(self):
        ticks = feed.parse_simple_price(SAMPLE)
        self.assertEqual([t["symbol"] for t in ticks], ["BTC-USD", "ETH-USD", "SOL-USD"])
        btc = ticks[0]
        self.assertEqual(btc["time"], datetime(2026, 10, 13, 22, 6, 24, tzinfo=timezone.utc))
        self.assertEqual(btc["price"], Decimal("83380.23728352188"))
        self.assertEqual(btc["volume_24h_usd"], Decimal("32780789488.952454"))

    def test_accepts_raw_json_text_and_bytes(self):
        text = json.dumps(SAMPLE)
        self.assertEqual(feed.parse_simple_price(text), feed.parse_simple_price(text.encode()))

    def test_prices_are_exact_decimals_not_floats(self):
        for t in feed.parse_simple_price(SAMPLE):
            self.assertIsInstance(t["price"], Decimal)

    def test_skips_missing_or_bad_rows(self):
        bad = {
            "bitcoin": {"usd": 0, "last_updated_at": 1791929184},
            "ethereum": {"usd": "abc", "last_updated_at": 1791929184},
            "solana": {"usd": 106.9},
        }
        self.assertEqual(feed.parse_simple_price(bad), [])
        self.assertEqual(feed.parse_simple_price({}), [])
        self.assertEqual(feed.parse_simple_price({"bitcoin": {"usd": True, "last_updated_at": 1}}), [])

    def test_missing_or_negative_volume_becomes_null(self):
        p = {"bitcoin": {"usd": 1.5, "last_updated_at": 1791929184, "usd_24h_vol": -3}}
        self.assertIsNone(feed.parse_simple_price(p)[0]["volume_24h_usd"])

    def test_rate_limit_body_raises(self):
        body = {"status": {"error_code": 429, "error_message": "You've exceeded the Rate Limit."}}
        with self.assertRaises(feed.RateLimited):
            feed.parse_simple_price(body)
        with self.assertRaises(feed.FeedError):
            feed.parse_simple_price({"status": {"error_code": 500, "error_message": "oops"}})
        with self.assertRaises(feed.FeedError):
            feed.parse_simple_price([1, 2])


class DedupeAndPacing(unittest.TestCase):
    def test_new_ticks_drops_repeats_of_the_same_update(self):
        seen = {}
        first = feed.parse_simple_price(SAMPLE)
        self.assertEqual(len(feed.new_ticks(first, seen)), 3)
        self.assertEqual(feed.new_ticks(first, seen), [])
        later = json.loads(json.dumps(SAMPLE))
        later["solana"]["last_updated_at"] += 30
        fresh = feed.new_ticks(feed.parse_simple_price(later), seen)
        self.assertEqual([t["symbol"] for t in fresh], ["SOL-USD"])

    def test_never_faster_than_one_request_per_second(self):
        self.assertEqual(feed.clamp_interval(0), 1.0)
        self.assertEqual(feed.clamp_interval(0.2), 1.0)
        self.assertEqual(feed.clamp_interval(20), 20.0)
        self.assertGreaterEqual(feed.DEFAULT_INTERVAL_S, 1.0)

    def test_backoff_grows_and_is_capped(self):
        steps = [feed.backoff_seconds(n, 20) for n in range(1, 8)]
        self.assertEqual(steps[:3], [20, 40, 80])
        self.assertEqual(max(steps), feed.MAX_BACKOFF_S)
        self.assertEqual(steps, sorted(steps))

    def test_url_is_keyless_and_asks_for_the_needed_fields(self):
        url = feed.build_url(list(feed.COINS))
        self.assertTrue(url.startswith("https://api.coingecko.com/api/v3/simple/price?"))
        for part in ["ids=bitcoin,ethereum,solana", "vs_currencies=usd", "include_last_updated_at=true", "include_24hr_vol=true"]:
            self.assertIn(part, url)
        self.assertNotIn("key", url.lower())


class FinanceSchema(unittest.TestCase):
    def setUp(self):
        self.sql = read(ROOT / "finance" / "schema.sql")
        self.flat = norm(strip_sql(self.sql))

    def test_statements_are_terminated(self):
        stmts, tail = statements(self.sql)
        self.assertEqual(len(stmts), 3)
        self.assertEqual(tail, "")

    def test_ticks_table_is_a_hypertable_keyed_on_symbol_and_time(self):
        self.assertIn("CREATE TABLE IF NOT EXISTS crypto_ticks", self.flat)
        self.assertIn("tsdb.hypertable", self.flat)
        self.assertIn("PRIMARY KEY (symbol, time)", self.flat)

    def test_one_minute_ohlc_continuous_aggregate(self):
        for part in ["timescaledb.continuous", "time_bucket('', time) AS bucket", "first(price, time) AS open",
                     "max(price) AS high", "min(price) AS low", "last(price, time) AS close",
                     "add_continuous_aggregate_policy('', "]:
            self.assertIn(part, self.flat)
        self.assertIn("time_bucket('1 minute', time)", self.sql)

    def test_ingester_insert_matches_table_columns(self):
        ingest = read(ROOT / "finance" / "ingest.py")
        self.assertIn("INSERT INTO crypto_ticks (time, symbol, price, volume_24h_usd)", ingest)
        self.assertIn("ON CONFLICT (symbol, time) DO NOTHING", ingest)
        self.assertNotIn("DROP", self.flat.upper())


if __name__ == "__main__":
    unittest.main()
