"""finance/query.py helpers: formatting and plain-text table rendering (offline only)."""
import sys
import unittest
from decimal import Decimal

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
