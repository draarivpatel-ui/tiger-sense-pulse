"""Sensor Pulse: semantic search over maintenance notes with pgvector + pgvectorscale on Tiger Cloud.

Usage: DATABASE_URL=postgres://... python vector/vector_search.py [--load]
Embeddings are computed locally with fastembed (BAAI/bge-small-en-v1.5, 384 dims), so no API key is needed.
"""
import os, sys
from pathlib import Path
import psycopg
from fastembed import TextEmbedding
from notes import NOTES

HERE = Path(__file__).parent
model = TextEmbedding("BAAI/bge-small-en-v1.5")

def emb(texts):
    return ["[" + ",".join(f"{x:.6f}" for x in v) + "]" for v in model.embed(texts)]

QUERIES = [
    # (question, extra SQL filter, params, label)
    ("the air conditioning broke and the room overheated", "", (), "All notes"),
    ("plants damaged by heat", "AND n.time >= '2026-10-07' AND n.time < '2026-10-08'", (), "Only Oct 7 (time filter)"),
    ("something is making noise or vibrating", "AND s.type = 'indoor'", (), "Indoor sensors only (metadata filter)"),
]

with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True) as conn:
    cur = conn.cursor()
    if "--load" in sys.argv:
        cur.execute((HERE / "05_vector_schema.sql").read_text())
        cur.execute("TRUNCATE maintenance_notes")
        vecs = emb([n[3] for n in NOTES])
        cur.executemany(
            "INSERT INTO maintenance_notes (time, sensor_id, author, note, embedding) VALUES (%s::timestamptz AT TIME ZONE 'UTC', %s, %s, %s, %s::vector)",
            [(t + ":00", sid, a, note, v) for (t, sid, a, note), v in zip(NOTES, vecs)],
        )
        print(f"Loaded {len(NOTES)} notes with 384-dim embeddings.")
    cur.execute("SELECT extversion FROM pg_extension WHERE extname='vector'"); print("pgvector", cur.fetchone()[0])
    cur.execute("SELECT extversion FROM pg_extension WHERE extname='vectorscale'"); print("pgvectorscale", cur.fetchone()[0])
    for q, filt, params, label in QUERIES:
        (qv,) = emb([q])
        print(f"\n=== \"{q}\"  [{label}]")
        # Similarity search joined back to the time series: what was the temperature that hour?
        cur.execute(f"""
            SELECT n.time, s.name, round((1 - (n.embedding <=> %s::vector))::numeric, 3) AS similarity,
                   n.note, h.max_temp
            FROM maintenance_notes n
            JOIN sensors s ON s.id = n.sensor_id
            LEFT JOIN sensor_hourly h ON h.sensor_id = n.sensor_id AND h.bucket = time_bucket('1 hour', n.time)
            WHERE true {filt}
            ORDER BY n.embedding <=> %s::vector
            LIMIT 3""", (qv, *params, qv))
        for t, name, sim, note, mt in cur.fetchall():
            print(f"  {t:%b %d %H:%M} UTC | {name:<10} | sim {sim} | hour max {mt if mt is not None else '-'} C | {note}")
    cur.execute("SET enable_seqscan = off")
    (qv,) = emb(["air conditioner failure"])
    cur.execute("EXPLAIN SELECT note FROM maintenance_notes ORDER BY embedding <=> %s::vector LIMIT 3", (qv,))
    print("\nQuery plan (seqscan disabled to show the index):")
    import re
    for (line,) in cur.fetchall(): print("  " + re.sub(r"'\[[^\]]*\]'", "'[...384 floats...]'", line))
