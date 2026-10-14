# dashboard.py edge-case test spec

Observed by calling `svg_chart` directly in Python (psycopg stubbed), 2026-10-13. No app behavior changed.

| # | Input | Observed | Verdict |
|---|-------|----------|---------|
| D1 | `{}` or `{"a": []}` | hint paragraph "No data yet" | covered by test_empty_series |
| D2 | one timestamp | no ZeroDivision (`max(t1-t0,1)`) | covered |
| D3 | all values equal (flat line) | `lo/hi` padded by ±1, no divide by zero | covered by test_flat_line_and_single_timestamp_give_finite_coordinates |
| D4 | NaN value | no exception, but polyline contains `nan` coordinates (invalid SVG, line vanishes) | fixed 2026-10-14: `svg_chart` drops non-finite values and `main` skips NULL `avg_temp`; covered by test_nan_and_inf_values_are_dropped_not_drawn + test_null_hourly_average_is_skipped_by_main |
| D5 | naive datetimes | works (timestamp() uses local tz); DB returns tz-aware, so low risk | document |
| D6 | >6 sensors | colors cycle by modulo | covered |
| D7 | sensor name with HTML | escaped in legend and tables | covered |
| D8 | empty DB in `main` | page still written, anomaly row says "No anomalies found." | covered |
| D9 | tz label | anomaly hours print "UTC" but come from DB bucket tz; correct only if session tz is UTC | fixed 2026-10-13: hours converted with `astimezone(utc)`; covered by test_anomaly_hour_is_printed_in_utc_even_if_session_tz_differs |

All three proposed tests (D3, D4, D9) are now in tests/test_dashboard.py.
