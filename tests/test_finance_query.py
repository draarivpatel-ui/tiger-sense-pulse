"""finance/query.py helpers: formatting and plain-text table rendering (offline only)."""
import contextlib
import datetime
import io
import sys
import unittest
from decimal import Decimal
from unittest import mock

from sqlutil import ROOT

sys.path.insert(0, str(ROOT / "finance"))
import query  # noqa: E402


class FormatHelpers(unittest.TestCase):
    def test_fmt_none_is_empty_string(self):
        self.assertEqual(query.fmt(None), "")

    def test_fmt_decimal_float_int_and_str(self):
        self.assertEqual(query.fmt(Decimal("12.3400")), "12.3400")
        self.assertEqual(query.fmt(3.5), "3.5")
        self.assertEqual(query.fmt(7), "7")
        self.assertEqual(query.fmt("BTC-USD"), "BTC-USD")

    def test_fmt_date_prints_the_date_part_only(self):
        # a datetime.date has strftime but no utcoffset: it must not take the datetime branch
        self.assertEqual(query.fmt(datetime.date(2026, 10, 13)), "2026-10-13")
        self.assertEqual(query.fmt(datetime.datetime(2026, 10, 13, 22, 6, 24)), "2026-10-13 22:06:24")
        self.assertEqual(query.fmt(datetime.datetime(2026, 10, 13, 22, 6, 24, tzinfo=datetime.timezone.utc)),
                         "2026-10-13 22:06:24+00")

    def test_fmt_aware_datetime_is_normalized_to_utc(self):
        chennai = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        aware = datetime.datetime(2026, 10, 13, 22, 0, tzinfo=chennai)
        self.assertEqual(query.fmt(aware), "2026-10-13 16:30:00+00")

    def test_fmt_strips_terminal_control_characters(self):
        self.assertEqual(query.fmt("safe\x1b[2J\x07text"), "safe[2Jtext")


class CliArguments(unittest.TestCase):
    def test_minutes_must_be_positive(self):
        for value in ["0", "-5"]:
            with self.subTest(value=value), mock.patch.object(sys, "argv", ["query.py", "--minutes", value]), \
                    contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as cm:
                    query.main()
                self.assertEqual(cm.exception.code, 2)


class TableHelpers(unittest.TestCase):
    def test_table_renders_aligned_header_and_rows(self):
        out = query.table(["col", "n"], [("x", 1), ("long", 22)])
        self.assertEqual(
            out,
            "\n".join(
                [
                    " col  | n ",
                    "------+----",
                    " x    | 1 ",
                    " long | 22",
                    "(2 rows)",
                ]
            ),
        )

    def test_table_handles_ragged_rows(self):
        out = query.table(["a", "b"], [("only-a",), ("x", "y", "extra-cell")])
        self.assertIn("only-a", out)
        self.assertIn("(2 rows)", out)

    def test_table_with_no_rows_keeps_header_and_zero_count(self):
        out = query.table(["name", "value"], [])
        self.assertEqual(
            out,
            "\n".join(
                [
                    " name | value",
                    "------+-------",
                    "(0 rows)",
                ]
            ),
        )


if __name__ == "__main__":
    unittest.main()
