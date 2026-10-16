"""README consistency: the numbers, paths and quoted output in README.md must match the repo (no database needed)."""
import re
import unittest

from sqlutil import ROOT, read

README = read(ROOT / "README.md")
TESTS_DIR = ROOT / "tests"


def discovered_test_count():
    loader = unittest.TestLoader()
    return loader.discover(str(TESTS_DIR), top_level_dir=str(TESTS_DIR)).countTestCases()


def fenced_blocks(text):
    return re.findall(r"```[^\n]*\n(.*?)```", text, re.S)


class ReadmeMatchesRepo(unittest.TestCase):
    def test_test_counts_match_the_suite(self):
        n = discovered_test_count()
        self.assertTrue("Ran %d tests" % n in README, "README step 1 must show 'Ran %d tests'" % n)
        self.assertTrue("\n%d tests, Python" % n in README, "'How it was tested' must say '%d tests, Python'" % n)
        trimmed = re.search(r"\((\d+) of the (\d+) `\.\.\. ok` lines trimmed", README)
        self.assertIsNotNone(trimmed, "trimmed-lines note missing")
        self.assertEqual(int(trimmed.group(2)), n)
        shown = sum(1 for line in fenced_blocks(README)[1].splitlines() if line.endswith(" ... ok"))
        self.assertEqual(int(trimmed.group(1)), n - shown)

    def test_per_file_counts_match(self):
        loader = unittest.TestLoader()
        for path, n in re.findall(r"\(`tests/(test_\w+\.py)`, (\d+) tests\)", README):
            with self.subTest(file=path):
                suite = loader.discover(str(TESTS_DIR), pattern=path, top_level_dir=str(TESTS_DIR))
                self.assertEqual(suite.countTestCases(), int(n))
        listed = set(re.findall(r"\(`tests/(test_\w+\.py)`, \d+ tests\)", README))
        on_disk = {p.name for p in TESTS_DIR.glob("test_*.py")}
        self.assertEqual(listed, on_disk, "every test file is described in 'How it was tested'")

    def test_files_block_paths_exist(self):
        block = README.split("## Files", 1)[1]
        block = fenced_blocks(block)[0]
        for line in block.splitlines():
            if not line.strip():
                continue
            for path in line.split("  ")[0].split(" / "):
                path = path.strip()
                with self.subTest(path=path):
                    self.assertTrue((ROOT / path.rstrip("/")).exists(), path)

    def test_backticked_repo_paths_exist(self):
        ext = r"\.(?:py|sh|sql|txt|html|png|yml)"
        paths = set(re.findall(r"`((?:[\w.-]+/)*[\w-]+%s)`" % ext, README))
        self.assertGreater(len(paths), 10)
        repo_files = {p.relative_to(ROOT).as_posix() for p in ROOT.rglob("*") if p.is_file() and ".git" not in p.parts}
        for p in sorted(x[2:] if x.startswith("./") else x for x in paths):
            with self.subTest(path=p):
                # A bare name (`vector_search.py`) may live in a subfolder; a path must exist exactly.
                ok = p in repo_files if "/" in p else any(f == p or f.endswith("/" + p) for f in repo_files)
                self.assertTrue(ok, p)

    def test_relative_markdown_links_resolve(self):
        links = [l for l in re.findall(r"\]\(([^)\s]+)\)", README) if not re.match(r"https?://|#|mailto:", l)]
        self.assertTrue(links, "expected at least the hero image")
        for l in links:
            with self.subTest(link=l):
                self.assertTrue((ROOT / l.split("#")[0]).exists(), l)

    def test_quoted_anomaly_table_matches_sample_output(self):
        sample = read(ROOT / "sample-output.txt").splitlines()
        start = next(i for i, l in enumerate(sample) if l.startswith("--- 5. Anomaly"))
        expected = [l.rstrip() for l in sample[start:start + 7]]
        quoted = next(b for b in fenced_blocks(README) if b.startswith("--- 5. Anomaly"))
        self.assertEqual([l.rstrip() for l in quoted.strip("\n").splitlines()], expected)

    def test_replay_output_matches_generator(self):
        from datetime import datetime, timezone
        from test_generator import anomalies, simulate
        data = simulate(datetime(2026, 10, 10, 23, tzinfo=timezone.utc), seed=1)
        lines = ["rows: %d" % len(data)] + [
            "anomaly: %s %s" % (name, hour.strftime("%Y-%m-%d %H:00 UTC")) for name, hour in anomalies(data)]
        quoted = next(b for b in fenced_blocks(README) if b.startswith("rows: "))
        self.assertEqual(quoted.strip().splitlines(), lines)
        self.assertTrue("{:,} rows".format(len(data)) in README, "row count missing from README")


    def test_incident_and_hour_counts_agree(self):
        # 2 incidents (distinct sensors) over 3 anomalous hours: generator, sample-output.txt query 5 and README agree.
        from datetime import datetime, timezone
        from test_generator import anomalies, simulate
        flagged = anomalies(simulate(datetime(2026, 10, 10, 23, tzinfo=timezone.utc), seed=1))
        hours, incidents = len(flagged), len({name for name, _ in flagged})
        sample = read(ROOT / "sample-output.txt").splitlines()
        start = next(i for i, l in enumerate(sample) if l.startswith("--- 5. Anomaly"))
        end = next(i for i in range(start, len(sample)) if re.match(r"\(\d+ rows?\)", sample[i]))
        rows = [l.split("|")[0].strip() for l in sample[start + 3:end] if "|" in l]
        self.assertEqual((len(rows), len(set(rows))), (hours, incidents))
        self.assertEqual(sample[end], "(%d rows)" % hours)
        words = {1: "one", 2: "two", 3: "three", 4: "four", 5: "five"}
        for phrase in ["exactly the %s injected hours" % words[hours],
                       "**exactly** the %d injected hours" % hours,
                       "exactly the %s injected incidents" % words[incidents],
                       "exactly the %d injected incidents found (%d anomalous hours in query 5)" % (incidents, hours),
                       "the %s incidents hidden in the data" % words[incidents],
                       "%s incidents are injected" % words[incidents],
                       "+ %d injected incidents" % incidents]:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, README)


    def test_daily_rollup_day_count_matches_sql_window(self):
        # README says 7 days of data but "16 rows (8 days × 2 sensors)" from sensor_daily. Both hold: the window in
        # 02_simulate.sql includes both ends and sensor_daily uses time_bucket('1 day') (UTC days), so it always
        # touches 8 UTC days; the last day is partial, and the first is too unless the run ends at 00:00 UTC.
        from datetime import datetime, timedelta, timezone
        from test_generator import parse_interval
        sim = read(ROOT / "sql" / "02_simulate.sql")
        caggs = read(ROOT / "sql" / "03_continuous_aggregates.sql")
        m = re.search(r"generate_series\(date_trunc\('hour', now\(\)\) - interval '([^']+)',\s*"
                      r"date_trunc\('hour', now\(\)\),\s*interval '([^']+)'\)", sim)
        self.assertIsNotNone(m, "simulation window not found in 02_simulate.sql")
        span, step = parse_interval(m.group(1)), parse_interval(m.group(2))
        daily = caggs[caggs.index("CREATE MATERIALIZED VIEW sensor_daily"):]
        self.assertIn("time_bucket('1 day', bucket) AS day", daily[:daily.index(";")])
        per_day = int(timedelta(days=1) / step)
        day_counts = set()
        end = datetime(2026, 1, 1, tzinfo=timezone.utc)
        for _ in range(365 * 24):                       # every whole-hour run time in 2026
            start = end - span                          # generate_series includes both ends
            self.assertEqual(span % step, timedelta(0))
            start_midnight = start.replace(hour=0, minute=0)
            end_midnight = end.replace(hour=0, minute=0)
            first = -(-(start_midnight + timedelta(days=1) - start) // step)   # readings on the first UTC day
            last = (end - end_midnight) // step + 1                            # readings on the last UTC day
            self.assertLess(last, per_day)
            self.assertEqual(first == per_day, end.hour == 0)
            day_counts.add((end_midnight - start_midnight).days + 1)
            end += timedelta(hours=1)
        self.assertEqual(len(day_counts), 1, day_counts)
        n_days = day_counts.pop()
        self.assertIn("**%d rows** (%d days × 2 sensors; " % (2 * n_days, n_days), README)
        self.assertIn("for %d days: " % span.days, README)
        self.assertIn("so it always touches %d UTC days" % n_days, README)

    def test_shown_ok_lines_are_the_real_first_and_last(self):
        # Step 1 shows the first 2 and last 2 `... ok` lines of `bash test.sh`; they must be the ids the suite runs
        # first and last (discovery order), in the Python 3.11+ verbose form the README quotes, so a rename can't
        # leave the README quoting a line the suite never prints.
        def flatten(suite):
            for t in suite:
                if isinstance(t, unittest.TestSuite):
                    yield from flatten(t)
                else:
                    yield t
        ids = [t.id() for t in flatten(unittest.TestLoader().discover(str(TESTS_DIR), top_level_dir=str(TESTS_DIR)))]
        self.assertEqual(len(ids), len(set(ids)))
        real = ["%s (%s) ... ok" % (i.rsplit(".", 1)[1], i) for i in ids]
        block = fenced_blocks(README)[1].splitlines()
        shown = [l for l in block if l.endswith(" ... ok")]
        self.assertEqual(shown, real[:2] + real[-2:])
        self.assertEqual(block[:5], real[:2] + ["..."] + real[-2:], "2 lines, '...', 2 lines, in that order")


if __name__ == "__main__":
    unittest.main()
