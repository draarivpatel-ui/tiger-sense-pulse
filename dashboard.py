"""Render a static HTML dashboard from the sensor_hourly continuous aggregate.

Usage:
    pip install "psycopg[binary]"
    DATABASE_URL=postgres://... python dashboard.py      # writes dashboard.html

The page only reads the continuous aggregates (never the raw hypertable), which
is the point of CAGGs: the dashboard query stays small no matter how much raw
data piles up. Charts are hand-drawn inline SVG, so there are no JS dependencies.
"""
import html
import math
import os
from datetime import datetime, timezone

import psycopg

COLORS = ["#38bdf8", "#34d399", "#a78bfa", "#fb923c", "#22d3ee", "#f87171"]
W, H, PAD = 900, 320, 40

HOURLY_SQL = """
SELECT s.name, s.location, h.bucket, h.avg_temp, h.min_temp, h.max_temp
FROM sensor_hourly h JOIN sensors s ON s.id = h.sensor_id
ORDER BY s.id, h.bucket
"""
SUMMARY_SQL = """
SELECT s.name, s.location,
       round(avg(d.avg_temp)::numeric, 1), round(min(d.min_temp)::numeric, 1),
       round(max(d.max_temp)::numeric, 1), sum(d.readings)::bigint
FROM sensor_daily d JOIN sensors s ON s.id = d.sensor_id
GROUP BY s.id, s.name, s.location ORDER BY s.id
"""
ANOMALY_SQL = """
WITH typical AS (
  SELECT sensor_id, extract(hour FROM bucket) AS hr,
         percentile_cont(0.5) WITHIN GROUP (ORDER BY avg_temp) AS median_temp
  FROM sensor_hourly GROUP BY sensor_id, hr
)
SELECT s.name, h.bucket, round(h.max_temp::numeric, 1) AS max_temp,
       round((h.avg_temp - t.median_temp)::numeric, 1) AS above_typical
FROM sensor_hourly h
JOIN typical t ON t.sensor_id = h.sensor_id AND t.hr = extract(hour FROM h.bucket)
JOIN sensors s ON s.id = h.sensor_id
WHERE h.avg_temp - t.median_temp > 4
ORDER BY h.bucket
"""


def svg_chart(series):
    """series: {name: [(datetime, value), ...]} -> inline SVG line chart.

    Non-finite values (NaN/inf) are dropped so they can't turn the SVG points into "nan"."""
    series = {n: [(t, v) for t, v in vals if math.isfinite(v)] for n, vals in series.items()}
    pts = [p for v in series.values() for p in v]
    if not pts:
        return "<p>No data yet. Run run.sh first.</p>"
    t0 = min(p[0] for p in pts).timestamp()
    t1 = max(p[0] for p in pts).timestamp()
    lo = min(p[1] for p in pts) - 1
    hi = max(p[1] for p in pts) + 1
    x = lambda t: PAD + (t.timestamp() - t0) / max(t1 - t0, 1) * (W - 2 * PAD)
    y = lambda v: H - PAD - (v - lo) / (hi - lo) * (H - 2 * PAD)
    out = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="Hourly average temperature">']
    for i in range(5):  # gridlines + labels
        v = lo + (hi - lo) * i / 4
        out.append(f'<line x1="{PAD}" x2="{W-PAD}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#1e293b"/>'
                   f'<text x="4" y="{y(v)+4:.1f}" font-size="11" fill="#94a3b8">{v:.0f}°</text>')
    for i, (name, vals) in enumerate(series.items()):
        d = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in vals)
        out.append(f'<polyline fill="none" stroke="{COLORS[i % len(COLORS)]}" stroke-width="1.75" points="{d}"/>')
    out.append("</svg>")
    legend = " ".join(
        f'<span><i style="background:{COLORS[i % len(COLORS)]}"></i>{html.escape(n)}</span>'
        for i, n in enumerate(series))
    return "\n".join(out) + f'<div class="legend">{legend}</div>'


def main():
    url = os.environ["DATABASE_URL"]
    with psycopg.connect(url) as conn:
        hourly = conn.execute(HOURLY_SQL).fetchall()
        summary = conn.execute(SUMMARY_SQL).fetchall()
        anomalies = conn.execute(ANOMALY_SQL).fetchall()

    series = {}
    for name, _loc, bucket, avg_t, _mn, _mx in hourly:
        if avg_t is None:  # an empty bucket can come back NULL; skip it instead of crashing on float(None)
            continue
        series.setdefault(name, []).append((bucket, float(avg_t)))

    rows = "".join(
        f"<tr><td>{html.escape(n)}</td><td>{html.escape(l)}</td><td>{a}</td><td>{mn}</td><td>{mx}</td><td>{r:,}</td></tr>"
        for n, l, a, mn, mx, r in summary)
    arows = "".join(
        f"<tr><td>{html.escape(n)}</td><td>{(b.astimezone(timezone.utc) if b.tzinfo else b):%a %b %d, %H:%M} UTC</td><td>{m} °C</td><td>+{z}</td></tr>"
        for n, b, m, z in anomalies) or '<tr><td colspan="4">No anomalies found.</td></tr>'

    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Sensor Pulse · Tiger Cloud IoT demo</title>
<style>
 :root{{color-scheme:dark;--bg:#090c10;--surface:#11161f;--border:#1e293b;--ink:#e2e8f0;--muted:#94a3b8;--accent:#38bdf8;--signal:#34d399}}
 *{{box-sizing:border-box}}
 ::selection{{background:rgba(56,189,248,.24);color:#f8fafc}}
 html{{scrollbar-width:thin;scrollbar-color:#334155 #090c10}}
 ::-webkit-scrollbar{{width:10px;height:10px}} ::-webkit-scrollbar-track{{background:#090c10}} ::-webkit-scrollbar-thumb{{background:#334155;border-radius:999px;border:2px solid #090c10}}
 :focus-visible{{outline:2px solid var(--accent);outline-offset:2px}}
 body{{font-family:ui-sans-serif,system-ui,-apple-system,"Segoe UI",Roboto,sans-serif;max-width:1020px;margin:2.25rem auto;padding:0 1.25rem 3rem;color:var(--ink);background:var(--bg);line-height:1.55;font-variant-numeric:tabular-nums;-webkit-font-smoothing:antialiased}}
 h1{{margin:0 0 .25rem;font-size:1.85rem;letter-spacing:-.025em;color:#f8fafc}}
 h2{{margin:2rem 0 .65rem;font-size:1.1rem;font-weight:600;letter-spacing:-.01em;color:#f1f5f9}}
 .sub{{color:var(--muted);margin:0 0 1.5rem;font-size:.92rem;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}
 code{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-size:.9em;color:var(--accent);background:rgba(56,189,248,.1);padding:.1rem .35rem;border-radius:4px}}
 svg{{width:100%;height:auto;background:var(--surface);border:1px solid var(--border);border-radius:8px;padding:.35rem;display:block}}
 svg text{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;font-variant-numeric:tabular-nums}}
 .legend{{display:flex;flex-wrap:wrap;gap:.5rem 1.15rem;margin-top:.65rem;padding:.55rem .85rem;background:var(--surface);border:1px solid var(--border);border-radius:6px;font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}
 .legend span{{display:inline-flex;align-items:center;font-size:.82rem;color:var(--ink)}} .legend i{{display:inline-block;width:10px;height:10px;margin-right:6px;border-radius:2px}}
 table{{border-collapse:collapse;width:100%;margin:.65rem 0 1.5rem;background:var(--surface);border:1px solid var(--border);border-radius:8px;overflow:hidden;font-variant-numeric:tabular-nums}}
 th,td{{text-align:left;padding:.55rem .8rem;border-bottom:1px solid var(--border);font-size:.92rem}}
 th{{background:#0d121a;color:var(--muted);font-weight:600;font-size:.82rem}}
 td{{font-family:ui-monospace,SFMono-Regular,Menlo,Consolas,monospace}}
 td:nth-child(2){{font-family:ui-sans-serif,system-ui,-apple-system,sans-serif;color:var(--muted)}}
 tr:last-child td{{border-bottom:0}}
 tr:hover td{{background:rgba(56,189,248,.04)}}
 @media (prefers-reduced-motion:reduce){{*,*::before,*::after{{animation-duration:.01ms!important;transition-duration:.01ms!important}}}}
</style></head><body>
<h1>Sensor Pulse</h1>
<p class="sub">Simulated school IoT sensors on TimescaleDB · generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC from continuous aggregates</p>
<h2>Hourly average temperature (°C), last 7 days</h2>
{svg_chart(series)}
<h2>Per-sensor summary (from <code>sensor_daily</code>)</h2>
<table><tr><th>Sensor</th><th>Location</th><th>Avg °C</th><th>Min °C</th><th>Max °C</th><th>Raw readings</th></tr>{rows}</table>
<h2>Anomalies (hourly average &gt; 4 °C above that sensor's typical reading for the same hour of day)</h2>
<table><tr><th>Sensor</th><th>Hour</th><th>Peak</th><th>Above typical (°C)</th></tr>{arows}</table>
</body></html>"""
    with open("dashboard.html", "w") as f:
        f.write(page)
    print(f"wrote dashboard.html ({len(hourly)} hourly rows, {len(anomalies)} anomalies)")


if __name__ == "__main__":
    main()
