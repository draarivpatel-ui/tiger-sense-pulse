# dashboard.py edge-case test spec

Observed by calling `svg_chart` directly in Python (psycopg stubbed), 2026-10-13. No app behavior changed.

| # | Input | Observed | Verdict |
|---|-------|----------|---------|
| D1 | `{}` or `{"a": []}` | hint paragraph "No data yet" | covered by test_empty_series |
| D2 | one timestamp | no ZeroDivision (`max(t1-t0,1)`) | covered by test_single_timestamp_does_not_divide_by_zero + test_flat_line_and_single_timestamp_give_finite_coordinates |
| D3 | all values equal (flat line) | `lo/hi` padded by ±1, no divide by zero | covered by test_flat_line_and_single_timestamp_give_finite_coordinates |
| D4 | NaN value | no exception, but polyline contains `nan` coordinates (invalid SVG, line vanishes) | fixed 2026-10-14: `svg_chart` drops non-finite values and `main` skips NULL `avg_temp`; covered by test_nan_and_inf_values_are_dropped_not_drawn + test_null_hourly_average_is_skipped_by_main |
| D5 | naive datetimes | works (timestamp() uses local tz); DB returns tz-aware, so low risk | covered 2026-10-14 by test_naive_datetimes_give_finite_coordinates (finite, in-viewBox, left-to-right x) |
| D6 | >6 sensors | colors cycle by modulo | covered by test_colors_cycle_and_legend_escapes_names (7 series, 7th stroke = 1st) |
| D7 | sensor name with HTML | escaped in legend and tables | legend: test_colors_cycle_and_legend_escapes_names; summary location: test_escapes_text_from_the_database; sensor name in summary + anomaly tables: test_sensor_name_with_html_is_escaped_in_both_tables (added 2026-10-14; before it only the location column was tested) |
| D8 | empty DB in `main` | page still written, anomaly row says "No anomalies found." | covered by test_empty_database_still_writes_a_page (2026-10-14: now also asserts the "No anomalies found." row, which it did not check before) |
| D9 | tz label | anomaly hours print "UTC" but come from DB bucket tz; correct only if session tz is UTC | fixed 2026-10-13: hours converted with `astimezone(utc)`; covered by test_anomaly_hour_is_printed_in_utc_even_if_session_tz_differs. Naive buckets (2026-10-14): unreachable today because `sensor_data.time` is TIMESTAMPTZ, so buckets are timestamptz and psycopg returns aware datetimes; if one ever appears it is printed unchanged and assumed UTC. Pinned by test_naive_anomaly_hour_is_assumed_utc_and_schema_keeps_buckets_tz_aware (column type + naive print). No `SET TIME ZONE` added: app code unchanged |

All three proposed tests (D3, D4, D9) are now in tests/test_dashboard.py. Every row D1–D9 now names its test (2026-10-14: +D5 and D7-tables tests, D8 assertion added; suite 70 tests, dashboard 17; +D9 naive-bucket test: suite 71, dashboard 18).
