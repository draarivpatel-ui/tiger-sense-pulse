"""Unit tests for dashboard.py, the static HTML generator. psycopg is stubbed, so no database or pip install is needed."""
import contextlib
import io
import math
import os
import re
import sys
import tempfile
import types
import unittest
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from unittest import mock

from sqlutil import ROOT

sys.modules.setdefault("psycopg", types.SimpleNamespace(connect=None))  # dashboard imports psycopg at load time
sys.path.insert(0, str(ROOT))
import dashboard  # noqa: E402

T0 = datetime(2026, 10, 3, 0, 0, tzinfo=timezone.utc)


class FakeConn:
    def __init__(self, hourly, summary, anomalies):
        self.results = {dashboard.HOURLY_SQL: hourly, dashboard.SUMMARY_SQL: summary, dashboard.ANOMALY_SQL: anomalies}
        self.queries = []

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def execute(self, sql):
        self.queries.append(sql)
        return types.SimpleNamespace(fetchall=lambda: self.results[sql])


def render(hourly, summary, anomalies):
    conn = FakeConn(hourly, summary, anomalies)
    with tempfile.TemporaryDirectory() as d, mock.patch.dict(os.environ, {"DATABASE_URL": "postgres://test"}), \
            mock.patch.object(dashboard.psycopg, "connect", lambda url: conn, create=True):
        cwd = os.getcwd()
        os.chdir(d)
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                dashboard.main()
            return Path(d, "dashboard.html").read_text(encoding="utf-8"), conn
        finally:
            os.chdir(cwd)


class SvgChart(unittest.TestCase):
    def test_empty_series_shows_a_hint_instead_of_a_chart(self):
        self.assertIn("No data yet", dashboard.svg_chart({}))
        self.assertIn("No data yet", dashboard.svg_chart({"lab-1": []}))

    def test_anomaly_hour_is_printed_in_utc_even_if_session_tz_differs(self):
        cdt = timezone(timedelta(hours=-5))
        b = datetime(2026, 10, 3, 20, 0, tzinfo=cdt)  # 01:00 UTC next day
        page, _ = render([], [], [("s", b, Decimal("40.1"), Decimal("3.2"))])
        self.assertIn("Sun Oct 04, 01:00 UTC", page)

    def test_flat_line_and_single_timestamp_give_finite_coordinates(self):
        flat = dashboard.svg_chart({"s": [(T0 + timedelta(hours=h), 21.0) for h in range(6)]})
        single = dashboard.svg_chart({"s": [(T0, 21.0)]})
        for svg in (flat, single):
            self.assertNotIn("nan", svg.lower())
            self.assertNotIn("inf", svg.lower())
            self.assertEqual(svg.count("<polyline"), 1)

    def test_nan_and_inf_values_are_dropped_not_drawn(self):
        vals = [(T0 + timedelta(hours=h), v) for h, v in enumerate([20.0, float("nan"), 22.0, float("inf"), 21.0])]
        svg = dashboard.svg_chart({"s": vals})
        self.assertNotIn("nan", svg.lower())
        self.assertNotIn("inf", svg.lower())
        pts = re.search(r'points="([^"]*)"', svg).group(1).split()
        self.assertEqual(len(pts), 3)
        self.assertIn("No data yet", dashboard.svg_chart({"s": [(T0, float("nan"))]}))

    def test_null_hourly_average_is_skipped_by_main(self):
        hourly = [("s", "lab", T0, Decimal("20.0"), None, None), ("s", "lab", T0 + timedelta(hours=1), None, None, None),
                  ("s", "lab", T0 + timedelta(hours=2), Decimal("21.0"), None, None)]
        page, _ = render(hourly, [], [])
        self.assertNotIn("nan", page.lower())
        self.assertEqual(len(re.search(r'points="([^"]*)"', page).group(1).split()), 2)

    def test_one_polyline_per_sensor_and_points_inside_the_viewbox(self):
        series = {f"s{i}": [(T0 + timedelta(hours=h), 20 + i + (h % 5)) for h in range(48)] for i in range(3)}
        svg = dashboard.svg_chart(series)
        self.assertEqual(svg.count("<polyline"), 3)
        self.assertIn('viewBox="0 0 %d %d"' % (dashboard.W, dashboard.H), svg)
        for pts in re.findall(r'points="([^"]+)"', svg):
            coords = [tuple(map(float, p.split(","))) for p in pts.split()]
            self.assertEqual(len(coords), 48)
            for x, y in coords:
                self.assertTrue(dashboard.PAD - 0.05 <= x <= dashboard.W - dashboard.PAD + 0.05, x)
                self.assertTrue(dashboard.PAD - 0.05 <= y <= dashboard.H - dashboard.PAD + 0.05, y)
            self.assertEqual([c[0] for c in coords], sorted(c[0] for c in coords), "time runs left to right")

    def test_hotter_reading_is_drawn_higher(self):
        svg = dashboard.svg_chart({"a": [(T0, 20.0), (T0 + timedelta(hours=1), 30.0)]})
        (p1, p2) = [tuple(map(float, p.split(","))) for p in re.search(r'points="([^"]+)"', svg).group(1).split()]
        self.assertLess(p2[1], p1[1])

    def test_single_timestamp_does_not_divide_by_zero(self):
        self.assertIn("<polyline", dashboard.svg_chart({"a": [(T0, 21.5)]}))

    def test_colors_cycle_and_legend_escapes_names(self):
        series = {f"<s{i}>": [(T0, 20.0)] for i in range(len(dashboard.COLORS) + 1)}
        svg = dashboard.svg_chart(series)
        self.assertIn("&lt;s0&gt;", svg)
        self.assertNotIn("<s0>", svg)
        strokes = re.findall(r'<polyline fill="none" stroke="(#[0-9a-f]{6})"', svg)
        self.assertEqual(strokes[-1], strokes[0])

    def test_naive_datetimes_give_finite_coordinates(self):
        naive = [(datetime(2026, 10, 3, h, 0), 20.0 + h) for h in range(4)]  # no tzinfo: timestamp() uses local tz
        svg = dashboard.svg_chart({"s": naive})
        self.assertNotIn("nan", svg.lower())
        self.assertNotIn("inf", svg.lower())
        coords = [tuple(map(float, p.split(","))) for p in re.search(r'points="([^"]+)"', svg).group(1).split()]
        self.assertEqual(len(coords), 4)
        for x, y in coords:
            self.assertTrue(math.isfinite(x) and math.isfinite(y), (x, y))
            self.assertTrue(dashboard.PAD - 0.05 <= x <= dashboard.W - dashboard.PAD + 0.05, x)
        self.assertEqual([c[0] for c in coords], sorted(c[0] for c in coords))

    def test_gridline_labels_span_the_data(self):
        svg = dashboard.svg_chart({"a": [(T0, 18.0), (T0 + timedelta(hours=1), 42.0)]})
        labels = [int(v) for v in re.findall(r">(-?\d+)°</text>", svg)]
        self.assertEqual(len(labels), 5)
        self.assertLessEqual(labels[0], 18)
        self.assertGreaterEqual(labels[-1], 42)


class DashboardPage(unittest.TestCase):
    HOURLY = [("greenhouse", "Science greenhouse", T0 + timedelta(hours=h), 27.0 + h, 26.0, 28.0) for h in range(3)] + \
             [("server-rm", "Server closet", T0 + timedelta(hours=h), Decimal("24.5"), 24.0, 25.0) for h in range(3)]
    SUMMARY = [("greenhouse", "Science greenhouse", Decimal("27.4"), Decimal("20.1"), Decimal("42.3"), 2017),
               ("server-rm", "Server <closet>", Decimal("24.6"), Decimal("21.0"), Decimal("38.6"), 2017)]
    ANOMALIES = [("greenhouse", datetime(2026, 10, 7, 19, 0, tzinfo=timezone.utc), Decimal("42.3"), Decimal("9.0"))]

    def test_page_has_chart_summary_and_anomaly_rows(self):
        page, conn = render(self.HOURLY, self.SUMMARY, self.ANOMALIES)
        self.assertTrue(page.startswith("<!doctype html>"))
        self.assertEqual(page.count("<polyline"), 2)
        self.assertIn("<td>greenhouse</td><td>Science greenhouse</td><td>27.4</td><td>20.1</td><td>42.3</td><td>2,017</td>", page)
        self.assertIn("<td>greenhouse</td><td>Wed Oct 07, 19:00 UTC</td><td>42.3 °C</td><td>+9.0</td>", page)
        self.assertNotIn("No anomalies found", page)

    def test_reads_only_the_continuous_aggregates(self):
        _, conn = render(self.HOURLY, self.SUMMARY, self.ANOMALIES)
        self.assertEqual(len(conn.queries), 3)
        for q in conn.queries:
            self.assertNotRegex(q, r"\bsensor_data\b", "dashboard must not scan the raw hypertable")
            self.assertRegex(q, r"\bsensor_(hourly|daily)\b")

    def test_escapes_text_from_the_database(self):
        page, _ = render(self.HOURLY, self.SUMMARY, self.ANOMALIES)
        self.assertIn("Server &lt;closet&gt;", page)
        self.assertNotIn("Server <closet>", page)

    def test_sensor_name_with_html_is_escaped_in_both_tables(self):
        summary = [("<b>s1</b>", "lab", Decimal("21.0"), Decimal("20.0"), Decimal("22.0"), 10)]
        anomalies = [("<b>s1</b>", datetime(2026, 10, 7, 19, 0, tzinfo=timezone.utc), Decimal("30.0"), Decimal("5.0"))]
        page, _ = render([], summary, anomalies)
        self.assertEqual(page.count("<td>&lt;b&gt;s1&lt;/b&gt;</td>"), 2)
        self.assertNotIn("<b>s1</b>", page)

    def test_no_anomalies_message(self):
        page, _ = render(self.HOURLY, self.SUMMARY, [])
        self.assertIn('<td colspan="4">No anomalies found.</td>', page)

    def test_empty_database_still_writes_a_page(self):
        page, _ = render([], [], [])
        self.assertIn("No data yet. Run run.sh first.", page)
        self.assertIn('<td colspan="4">No anomalies found.</td>', page)
        self.assertIn("</html>", page)


if __name__ == "__main__":
    unittest.main()
