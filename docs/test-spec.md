# dashboard.py edge-case test spec

Observed by calling `svg_chart` directly in Python (psycopg stubbed), 2026-10-13. No app behavior changed.

| # | Input | Observed | Verdict |
|---|-------|----------|---------|
| D1 | `{}` or `{"a": []}` | hint paragraph "No data yet" | covered by test_empty_series |
| D2 | one timestamp | no ZeroDivision (`max(t1-t0,1)`) | covered |
| D3 | all values equal (flat line) | `lo/hi` padded by ±1, no divide by zero | add test |
| D4 | NaN value | no exception, but polyline contains `nan` coordinates (invalid SVG, line vanishes) | gap; fix in SQL (`avg_temp IS NOT NULL`) or filter in `main` |
| D5 | naive datetimes | works (timestamp() uses local tz); DB returns tz-aware, so low risk | document |
| D6 | >6 sensors | colors cycle by modulo | covered |
| D7 | sensor name with HTML | escaped in legend and tables | covered |
| D8 | empty DB in `main` | page still written, anomaly row says "No anomalies found." | covered |
| D9 | tz label | anomaly hours print "UTC" but come from DB bucket tz; correct only if session tz is UTC | gap; assert `SET TIME ZONE 'UTC'` |

Proposed new tests: D3 (flat line has finite coordinates), D4 (no "nan" in output), D9.
