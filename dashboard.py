"""Render a static HTML dashboard from the sensor_hourly continuous aggregate.

Usage:
    pip install "psycopg[binary]"
    DATABASE_URL=postgres://... python dashboard.py      # writes dashboard.html

The page only reads the continuous aggregates (never the raw hypertable), which
is the point of CAGGs: the dashboard query stays small no matter how much raw
data piles up. Charts are hand-drawn inline SVG, so there are no JS dependencies.
"""
import html
import os
from datetime import datetime, timezone

import psycopg

COLORS = ["#2563eb", "#16a34a", "#9333ea", "#ea580c", "#0891b2", "#dc2626"]
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
    """series: {name: [(datetime, value), ...]} -> inline SVG line chart."""
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
        out.append(f'<line x1="{PAD}" x2="{W-PAD}" y1="{y(v):.1f}" y2="{y(v):.1f}" stroke="#e5e7eb"/>'
                   f'<text x="4" y="{y(v)+4:.1f}" font-size="11" fill="#6b7280">{v:.0f}°</text>')
    for i, (name, vals) in enumerate(series.items()):
        d = " ".join(f"{x(t):.1f},{y(v):.1f}" for t, v in vals)
        out.append(f'<polyline fill="none" stroke="{COLORS[i % len(COLORS)]}" stroke-width="1.6" points="{d}"/>')
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
 body{{font-family:system-ui,sans-serif;max-width:960px;margin:2rem auto;padding:0 1rem;color:#111827}}
 h1{{margin-bottom:.2rem}} .sub{{color:#6b7280;margin-top:0}}
 svg{{width:100%;height:auto;border:1px solid #e5e7eb;border-radius:8px}}
 .legend span{{margin-right:1rem;font-size:.85rem}} .legend i{{display:inline-block;width:10px;height:10px;margin-right:4px;border-radius:2px}}
 table{{border-collapse:collapse;width:100%;margin:1rem 0}} th,td{{text-align:left;padding:.4rem .6rem;border-bottom:1px solid #e5e7eb}}
 th{{background:#f9fafb}}
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
