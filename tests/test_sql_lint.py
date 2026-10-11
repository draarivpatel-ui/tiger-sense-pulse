"""SQL file lint: structure and consistency checks on sql/*.sql and vector/*.sql (no database needed)."""
import re
import unittest

from sqlutil import ROOT, SQL_DIR, SQL_FILES, norm, read, statements, strip_sql

DEMO_OBJECTS = {"sensors", "sensor_data", "sensor_hourly", "sensor_daily"}


def columns_of_create_table(text, table):
    m = re.search(r"CREATE TABLE (?:IF NOT EXISTS )?%s\s*\((.*?)\)\s*(?:WITH|;)" % table, strip_sql(text), re.S | re.I)
    assert m, table
    cols = []
    for line in m.group(1).split(","):
        word = line.strip().split()[0] if line.strip() else ""
        if word and word.upper() not in {"PRIMARY", "UNIQUE", "CONSTRAINT", "FOREIGN"}:
            cols.append(word)
    return cols


def columns_of_cagg(text, view):
    m = re.search(r"CREATE MATERIALIZED VIEW %s\b.*?SELECT(.*?)FROM" % view, strip_sql(text), re.S | re.I)
    assert m, view
    cols = []
    for expr in re.split(r",\s*\n", m.group(1).strip()):
        alias = re.search(r"\bAS\s+(\w+)\s*$", expr.strip(), re.I)
        cols.append(alias.group(1) if alias else expr.strip())
    return cols


class SqlFileLint(unittest.TestCase):
    def test_expected_files_exist(self):
        names = [p.name for p in SQL_FILES]
        for f in ["01_schema.sql", "02_simulate.sql", "03_continuous_aggregates.sql", "04_queries.sql", "05_vector_schema.sql"]:
            self.assertIn(f, names)

    def test_files_are_clean_utf8_text(self):
        for p in SQL_FILES:
            with self.subTest(file=p.name):
                raw = p.read_bytes()
                raw.decode("utf-8")
                self.assertNotIn(b"\t", raw, "use spaces, not tabs")
                self.assertNotIn(b"\r", raw, "use LF line endings")
                self.assertTrue(raw.endswith(b"\n"), "file should end with a newline")
                self.assertTrue(raw.lstrip().startswith(b"--"), "file should open with a comment header")

    def test_strings_and_comments_are_terminated(self):
        for p in SQL_FILES:
            with self.subTest(file=p.name):
                strip_sql(read(p))  # raises on an unterminated string or /* comment

    def test_parentheses_balance(self):
        for p in SQL_FILES:
            with self.subTest(file=p.name):
                depth = 0
                for ch in strip_sql(read(p)):
                    depth += ch == "("
                    depth -= ch == ")"
                    self.assertGreaterEqual(depth, 0, "a ')' closes nothing")
                self.assertEqual(depth, 0, "unclosed '('")

    def test_every_statement_ends_with_semicolon(self):
        for p in SQL_FILES:
            with self.subTest(file=p.name):
                stmts, tail = statements(read(p))
                self.assertTrue(stmts, "no statements found")
                self.assertEqual(tail, "", "text after the last ';': %r" % tail[:60])

    def test_psql_meta_commands_only_in_queries_file(self):
        # The Tiger Console SQL editor does not understand \echo; README says only 04 uses it.
        for p in SQL_FILES:
            metas = [l for l in read(p).splitlines() if l.lstrip().startswith("\\")]
            with self.subTest(file=p.name):
                if p.name == "04_queries.sql":
                    self.assertTrue(all(l.startswith("\\echo '") and l.endswith("'") for l in metas), metas)
                else:
                    self.assertEqual(metas, [])

    def test_drops_only_touch_demo_objects(self):
        for p in SQL_FILES:
            for m in re.finditer(r"\bDROP\s+(?:MATERIALIZED\s+VIEW|TABLE|VIEW|INDEX)\s+(?:IF\s+EXISTS\s+)?(\w+)", strip_sql(read(p)), re.I):
                with self.subTest(file=p.name, obj=m.group(1)):
                    self.assertIn(m.group(1), DEMO_OBJECTS)
            self.assertNotRegex(strip_sql(read(p)), r"(?i)\b(DROP\s+(DATABASE|SCHEMA|EXTENSION)|TRUNCATE)\b")

    def test_drops_are_if_exists_so_reruns_are_safe(self):
        for m in re.finditer(r"\bDROP\s+[^;]*", strip_sql(read(SQL_DIR / "01_schema.sql")), re.I):
            self.assertIn("IF EXISTS", m.group(0).upper())

    def test_no_secrets_or_connection_strings(self):
        for p in list(SQL_FILES) + [ROOT / "run.sh", ROOT / "dashboard.py", ROOT / "vector" / "vector_search.py"]:
            text = read(p)
            with self.subTest(file=p.name):
                for pw in re.findall(r"postgres(?:ql)?://[^\s\"'/:@]*:([^\s\"'@]+)@", text):
                    self.assertTrue(pw == "..." or pw.startswith("<"), "hard-coded password in a URL")
                self.assertNotRegex(text, r"(?i)password\s*=\s*'[^']+'")

    def test_run_sh_applies_the_four_files_in_order(self):
        run = read(ROOT / "run.sh")
        listed = re.findall(r"sql/\d\d_\w+\.sql", run)
        self.assertEqual(listed, ["sql/01_schema.sql", "sql/02_simulate.sql", "sql/03_continuous_aggregates.sql", "sql/04_queries.sql"])
        for f in listed:
            self.assertTrue((ROOT / f).exists(), f)
        self.assertIn("ON_ERROR_STOP=1", run)
        self.assertIn("set -euo pipefail", run)

    def test_schema_matches_readme_table(self):
        schema, caggs, readme = read(SQL_DIR / "01_schema.sql"), read(SQL_DIR / "03_continuous_aggregates.sql"), read(ROOT / "README.md")
        actual = {
            "sensors": columns_of_create_table(schema, "sensors"),
            "sensor_data": columns_of_create_table(schema, "sensor_data"),
            "sensor_hourly": columns_of_cagg(caggs, "sensor_hourly"),
            "sensor_daily": columns_of_cagg(caggs, "sensor_daily"),
        }
        for obj, cols in actual.items():
            row = re.search(r"^\| `%s` \([^)]*\) \| (.*) \|$" % obj, readme, re.M)
            with self.subTest(obj=obj):
                self.assertIsNotNone(row, "README schema table row missing")
                self.assertEqual(re.findall(r"`(\w+)`", row.group(1)), cols)

    def test_sensor_data_is_a_hypertable_and_caggs_are_continuous(self):
        schema = norm(strip_sql(read(SQL_DIR / "01_schema.sql")))
        self.assertIn("tsdb.hypertable", schema)
        raw = read(SQL_DIR / "01_schema.sql")
        self.assertRegex(raw, r"tsdb\.segmentby\s*=\s*'sensor_id'")
        self.assertRegex(raw, r"tsdb\.chunk_interval\s*=\s*'1 day'")
        caggs = norm(strip_sql(read(SQL_DIR / "03_continuous_aggregates.sql")))
        self.assertEqual(caggs.count("WITH (timescaledb.continuous)"), 2)
        self.assertIn("FROM sensor_hourly GROUP BY day", caggs, "sensor_daily should be hierarchical (built on sensor_hourly)")
        self.assertEqual(caggs.count("add_continuous_aggregate_policy"), 2)
        self.assertEqual(caggs.count("CALL refresh_continuous_aggregate"), 2)

    def test_every_alias_column_exists(self):
        """In every query (04_queries.sql, dashboard.py, vector_search.py), alias.column must be a real column."""
        schema, caggs = read(SQL_DIR / "01_schema.sql"), read(SQL_DIR / "03_continuous_aggregates.sql")
        cols = {
            "sensors": set(columns_of_create_table(schema, "sensors")),
            "sensor_data": set(columns_of_create_table(schema, "sensor_data")),
            "sensor_hourly": set(columns_of_cagg(caggs, "sensor_hourly")),
            "sensor_daily": set(columns_of_cagg(caggs, "sensor_daily")),
            "maintenance_notes": set(columns_of_create_table(read(ROOT / "vector" / "05_vector_schema.sql"), "maintenance_notes")),
            "typical": {"sensor_id", "hr", "median_temp"},  # CTE in the anomaly query
        }
        queries = [(SQL_DIR / "04_queries.sql", q) for q in statements(read(SQL_DIR / "04_queries.sql"))[0]]
        for py in [ROOT / "dashboard.py", ROOT / "vector" / "vector_search.py"]:
            queries += [(py, q) for q in re.findall(r'"""(.*?)"""', read(py), re.S) if re.search(r"\bSELECT\b", q)]
        checked = 0
        for path, q in queries:
            aliases = {a: t for t, a in re.findall(r"\b(?:FROM|JOIN)\s+(\w+)\s+(?!ON\b|WHERE\b|GROUP\b|ORDER\b|JOIN\b)(\w+)", q, re.I)}
            for alias, col in re.findall(r"\b([a-z])\.(\w+)", q):
                with self.subTest(file=path.name, ref=alias + "." + col):
                    self.assertIn(alias, aliases, "alias not defined in this query")
                    self.assertIn(col, cols[aliases[alias]])
                    checked += 1
        self.assertGreater(checked, 30)
        self.assertNotIn("temperature_c", read(SQL_DIR / "04_queries.sql") + read(ROOT / "dashboard.py"))

    def test_dashboard_and_sql_anomaly_queries_match(self):
        # The README promises the dashboard shows the same anomalies as query 5.
        q = read(SQL_DIR / "04_queries.sql")
        sql_anomaly = q[q.index("WITH typical AS"):]
        sql_anomaly = sql_anomaly[: sql_anomaly.index(";")]
        dash = read(ROOT / "dashboard.py")
        dash_anomaly = re.search(r'ANOMALY_SQL = """(.*?)"""', dash, re.S).group(1)
        self.assertEqual(norm(sql_anomaly), norm(dash_anomaly))

    def test_vector_schema(self):
        v = norm(strip_sql(read(ROOT / "vector" / "05_vector_schema.sql")))
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vector", v)
        self.assertIn("CREATE EXTENSION IF NOT EXISTS vectorscale CASCADE", v)
        self.assertIn("embedding VECTOR(384) NOT NULL", v)
        self.assertIn("USING diskann (embedding vector_cosine_ops)", v)


if __name__ == "__main__":
    unittest.main()
