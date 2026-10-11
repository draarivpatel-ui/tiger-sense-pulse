"""Unit tests for the data generators: the IoT simulation in sql/02_simulate.sql and the notes in vector/notes.py.

The simulation runs inside Postgres, so these tests read its constants straight out of the SQL file and replay
the same formulas in Python (with seeded noise). If someone edits the SQL, the tests follow the edit and check
that the promises in the README still hold: 12,102 rows, warmest at 3 PM US Central, and the anomaly finder
catching exactly the injected incidents with no false positives.
"""
import math
import random
import re
import statistics
import sys
import unittest
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from sqlutil import ROOT, SQL_DIR, read

SIM = read(SQL_DIR / "02_simulate.sql")
SCHEMA = read(SQL_DIR / "01_schema.sql")
QUERIES = read(SQL_DIR / "04_queries.sql")


def parse_interval(text):
    total = timedelta()
    for n, unit in re.findall(r"(\d+)\s*(minute|hour|day)s?", text):
        total += {"minute": timedelta(minutes=1), "hour": timedelta(hours=1), "day": timedelta(days=1)}[unit] * int(n)
    assert total, text
    return total


def sensors():
    block = SCHEMA[SCHEMA.index("INSERT INTO sensors"):]
    rows = re.findall(r"\('([\w-]+)',\s*'(\w+)',\s*'([^']+)',\s*([\d.]+),\s*([\d.]+)\)", block)
    return [dict(name=n, type=t, location=l, base=float(b), swing=float(s)) for n, t, l, b, s in rows]


def constants():
    phase = float(re.search(r"extract\(epoch FROM g\.t\) / 86400\.0 - ([\d.]+)\)\)", SIM).group(1))
    noise = float(re.search(r"\+ \(random\(\) - 0\.5\) \* ([\d.]+)\)::numeric, 2\)", SIM).group(1))
    m = re.search(r"generate_series\(date_trunc\('hour', now\(\)\) - interval '([^']+)',\s*date_trunc\('hour', now\(\)\),\s*interval '([^']+)'\)", SIM)
    span, step = parse_interval(m.group(1)), parse_interval(m.group(2))
    hum = re.search(r"greatest\((\d+), least\((\d+),\s*(\d+) - (\d+) \* sin", SIM)
    incidents = []
    for m in re.finditer(r"UPDATE sensor_data SET temperature = temperature \+ (\d+).*?name = '([\w-]+)'.*?"
                         r"BETWEEN date_trunc\('hour', now\(\)\) - interval '([^']+)'\s*AND date_trunc\('hour', now\(\)\) - interval '([^']+)'", SIM, re.S):
        incidents.append(dict(add=float(m.group(1)), sensor=m.group(2), start=parse_interval(m.group(3)), end=parse_interval(m.group(4))))
    threshold = float(re.search(r"WHERE h\.avg_temp - t\.median_temp > (\d+(?:\.\d+)?)", QUERIES).group(1))
    return dict(phase=phase, noise=noise, span=span, step=step, hum_lo=int(hum.group(1)), hum_hi=int(hum.group(2)),
                hum_mid=int(hum.group(3)), hum_amp=int(hum.group(4)), incidents=incidents, threshold=threshold)


C = constants()


def simulate(now, seed):
    """Python replay of 02_simulate.sql -> {(sensor, time): temperature}."""
    rnd = random.Random(seed)
    end = now.replace(minute=0, second=0, microsecond=0)
    start = end - C["span"]
    data = {}
    t = start
    while t <= end:
        frac = t.timestamp() / 86400.0 - C["phase"]
        for s in sensors():
            data[(s["name"], t)] = round(s["base"] + s["swing"] * math.sin(2 * math.pi * frac) + (rnd.random() - 0.5) * C["noise"], 2)
        t += C["step"]
    for inc in C["incidents"]:
        lo, hi = end - inc["start"], end - inc["end"]
        for (name, ts) in list(data):
            if name == inc["sensor"] and lo <= ts <= hi:  # SQL BETWEEN is inclusive
                data[(name, ts)] += inc["add"]
    return data


def anomalies(data):
    """Replay of the anomaly query (04_queries.sql #5) on top of an hourly rollup like sensor_hourly."""
    buckets = defaultdict(list)
    for (name, ts), v in data.items():
        buckets[(name, ts.replace(minute=0))].append(v)
    hourly = {k: sum(v) / len(v) for k, v in buckets.items()}
    by_hour = defaultdict(list)
    for (name, b), avg in hourly.items():
        by_hour[(name, b.hour)].append(avg)
    typical = {k: statistics.median(v) for k, v in by_hour.items()}  # percentile_cont(0.5) == median
    return sorted((name, b) for (name, b), avg in hourly.items() if avg - typical[(name, b.hour)] > C["threshold"])


class SimulationGenerator(unittest.TestCase):
    def test_six_sensors_with_distinct_names_and_known_types(self):
        s = sensors()
        self.assertEqual(len(s), 6)
        self.assertEqual(len({x["name"] for x in s}), 6)
        self.assertTrue({x["type"] for x in s} <= {"indoor", "outdoor", "server"})
        self.assertEqual(sum(x["type"] == "server" for x in s), 1)

    def test_row_count_matches_readme_and_sample_output(self):
        timestamps = C["span"] // C["step"] + 1  # generate_series includes both ends
        self.assertEqual(timestamps, 2017)
        rows = timestamps * len(sensors())
        self.assertEqual(rows, 12102)
        self.assertIn("12,102 rows", read(ROOT / "README.md"))
        self.assertIn("12102", read(ROOT / "sample-output.txt"))
        self.assertIn("6 sensors x 2,017 timestamps = 12,102 rows", SIM)

    def test_replay_produces_one_reading_per_sensor_per_step(self):
        data = simulate(datetime(2026, 10, 10, 23, 30, tzinfo=timezone.utc), seed=1)
        self.assertEqual(len(data), 12102)

    def test_daily_peak_is_3pm_us_central(self):
        # sin(2*pi*(f - phase)) peaks when f - phase = 0.25 of a day
        peak_utc_hours = ((0.25 + C["phase"]) % 1) * 24
        self.assertAlmostEqual(peak_utc_hours, 20.0, delta=10 / 60)  # within 10 minutes of 20:00 UTC
        oct_day = datetime(2026, 10, 7, 20, 0, tzinfo=timezone.utc).astimezone(ZoneInfo("America/Chicago"))
        self.assertEqual(oct_day.hour, 15)

    def test_values_stay_in_plausible_ranges(self):
        for s in sensors():
            with self.subTest(sensor=s["name"]):
                lo = s["base"] - s["swing"] - C["noise"] / 2
                hi = s["base"] + s["swing"] + C["noise"] / 2 + max([i["add"] for i in C["incidents"] if i["sensor"] == s["name"]] or [0])
                self.assertGreater(lo, 10)
                self.assertLess(hi, 45)
        data = simulate(datetime(2026, 10, 10, 23, 30, tzinfo=timezone.utc), seed=2)
        self.assertLess(max(data.values()), 45)
        self.assertGreater(min(data.values()), 10)
        # humidity: 60 +/- 15 +/- 5 never reaches the 5..100 clamp
        self.assertGreaterEqual(C["hum_mid"] - C["hum_amp"] - 5, C["hum_lo"])
        self.assertLessEqual(C["hum_mid"] + C["hum_amp"] + 5, C["hum_hi"])

    def test_incidents_target_real_sensors_inside_the_window_and_do_not_overlap(self):
        names = {s["name"] for s in sensors()}
        inc = C["incidents"]
        self.assertEqual([i["sensor"] for i in inc], ["greenhouse", "server-rm"])
        for i in inc:
            with self.subTest(sensor=i["sensor"]):
                self.assertIn(i["sensor"], names)
                self.assertGreater(i["start"], i["end"], "BETWEEN start must be earlier than end")
                self.assertLess(i["start"], C["span"])
                self.assertGreater(i["add"], C["threshold"] + C["noise"], "spike must clear the anomaly threshold")
        self.assertTrue(inc[0]["end"] > inc[1]["start"], "incident windows should not overlap")

    def test_anomaly_finder_catches_exactly_the_injected_hours(self):
        # README: greenhouse flagged for two hours, server closet for one hour, no false positives.
        for seed in range(25):
            now = datetime(2026, 10, 10, 23, 30, tzinfo=timezone.utc) + timedelta(hours=seed * 7)
            end = now.replace(minute=0, second=0, microsecond=0)
            found = anomalies(simulate(now, seed))
            expected = [("greenhouse", end - timedelta(days=3, hours=4)), ("greenhouse", end - timedelta(days=3, hours=3)),
                        ("server-rm", end - timedelta(days=1, hours=6))]
            with self.subTest(seed=seed):
                self.assertEqual(found, sorted(expected))

    def test_threshold_is_the_same_in_sql_and_dashboard(self):
        dash = read(ROOT / "dashboard.py")
        self.assertIn("WHERE h.avg_temp - t.median_temp > %g" % C["threshold"], dash)
        self.assertIn("more than %g °C above" % C["threshold"], read(ROOT / "README.md"))


sys.path.insert(0, str(ROOT / "vector"))
from notes import NOTES  # noqa: E402


class NotesGenerator(unittest.TestCase):
    def test_thirty_well_formed_notes(self):
        self.assertEqual(len(NOTES), 30)
        for t, sensor, author, note in NOTES:
            with self.subTest(note=note[:30]):
                datetime.strptime(t, "%Y-%m-%d %H:%M")
                self.assertTrue(author.strip() and note.strip())
                self.assertLess(len(note), 200)
        self.assertEqual(len({n[3] for n in NOTES}), 30, "duplicate note text")

    def test_notes_are_chronological_and_inside_oct_4_to_10(self):
        times = [datetime.strptime(n[0], "%Y-%m-%d %H:%M") for n in NOTES]
        self.assertEqual(times, sorted(times))
        self.assertGreaterEqual(times[0], datetime(2026, 10, 4))
        self.assertLess(times[-1], datetime(2026, 10, 11))

    def test_every_note_names_a_real_sensor_and_every_sensor_has_notes(self):
        names = {s["name"] for s in sensors()}
        used = {n[1] for n in NOTES}
        self.assertTrue(used <= names, used - names)
        self.assertEqual(used, names)

    def test_incident_clusters_line_up_with_the_injected_incidents(self):
        gh = [n for n in NOTES if n[1] == "greenhouse" and n[0].startswith("2026-10-07") and n[0] >= "2026-10-07 18"]
        sv = [n for n in NOTES if n[1] == "server-rm" and n[0].startswith("2026-10-09") and n[0] >= "2026-10-09 16"]
        self.assertGreaterEqual(len(gh), 3)
        self.assertGreaterEqual(len(sv), 3)
        self.assertTrue(any("vent" in n[3].lower() for n in gh))
        self.assertTrue(any("air conditioner" in n[3].lower() or "ac " in n[3].lower() for n in sv))

    def test_loader_looks_sensor_ids_up_by_name(self):
        vs = read(ROOT / "vector" / "vector_search.py")
        self.assertIn("(SELECT id FROM sensors WHERE name = %s)", vs)


if __name__ == "__main__":
    unittest.main()
