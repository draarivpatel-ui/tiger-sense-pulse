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


if __name__ == "__main__":
    unittest.main()
