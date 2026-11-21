"""Sensor Pulse: semantic search over maintenance notes with pgvector + pgvectorscale on Tiger Cloud.

Usage: DATABASE_URL=postgres://... python vector/vector_search.py [--load]
Embeddings are computed locally with fastembed (BAAI/bge-small-en-v1.5, 384 dims), so no API key is needed.
"""
import os, re, sys
from pathlib import Path

HERE = Path(__file__).parent
_model = None

CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")


def emb(texts):
    """Embed texts with the local model, loaded lazily so importing this module
    for tests or lint checks never downloads model weights or opens a database."""
    global _model
    if _model is None:
        from fastembed import TextEmbedding
        _model = TextEmbedding("BAAI/bge-small-en-v1.5")
    return ["[" + ",".join(f"{x:.6f}" for x in v) + "]" for v in _model.embed(texts)]


def clean(value):
    """Strip terminal control characters out of database text before printing."""
    return CONTROL.sub("", str(value))


# Each search question carries its own complete SQL: the time/metadata filters
# are literals baked into the statement, so nothing is ever interpolated into SQL.
SEARCH_ALL = """
    SELECT n.time, s.name, round((1 - (n.embedding <=> %s::vector))::numeric, 3) AS similarity,
           n.note, h.max_temp
    FROM maintenance_notes n
    JOIN sensors s ON s.id = n.sensor_id
    LEFT JOIN sensor_hourly h ON h.sensor_id = n.sensor_id AND h.bucket = time_bucket('1 hour', n.time)
    ORDER BY n.embedding <=> %s::vector
    LIMIT 3"""
SEARCH_OCT7 = """
    SELECT n.time, s.name, round((1 - (n.embedding <=> %s::vector))::numeric, 3) AS similarity,
           n.note, h.max_temp
    FROM maintenance_notes n
    JOIN sensors s ON s.id = n.sensor_id
    LEFT JOIN sensor_hourly h ON h.sensor_id = n.sensor_id AND h.bucket = time_bucket('1 hour', n.time)
    WHERE n.time >= '2026-10-07' AND n.time < '2026-10-08'
    ORDER BY n.embedding <=> %s::vector
    LIMIT 3"""
SEARCH_INDOOR = """
    SELECT n.time, s.name, round((1 - (n.embedding <=> %s::vector))::numeric, 3) AS similarity,
           n.note, h.max_temp
    FROM maintenance_notes n
    JOIN sensors s ON s.id = n.sensor_id
    LEFT JOIN sensor_hourly h ON h.sensor_id = n.sensor_id AND h.bucket = time_bucket('1 hour', n.time)
    WHERE s.type = 'indoor'
    ORDER BY n.embedding <=> %s::vector
    LIMIT 3"""

QUERIES = [
    ("the air conditioning broke and the room overheated", SEARCH_ALL, "All notes"),
    ("plants damaged by heat", SEARCH_OCT7, "Only Oct 7 (time filter)"),
    ("something is making noise or vibrating", SEARCH_INDOOR, "Indoor sensors only (metadata filter)"),
]


def main():
    import psycopg
    from notes import NOTES

    with psycopg.connect(os.environ["DATABASE_URL"], autocommit=True, options="-c timezone=UTC") as conn:
        cur = conn.cursor()
        if "--load" in sys.argv:
            cur.execute((HERE / "05_vector_schema.sql").read_text())
            cur.execute("TRUNCATE maintenance_notes")
            vecs = emb([n[3] for n in NOTES])
            cur.executemany(
                "INSERT INTO maintenance_notes (time, sensor_id, author, note, embedding) VALUES (%s::timestamp AT TIME ZONE 'UTC', (SELECT id FROM sensors WHERE name = %s), %s, %s, %s::vector)",
                [(t + ":00", sensor, a, note, v) for (t, sensor, a, note), v in zip(NOTES, vecs)],
            )
            print(f"Loaded {len(NOTES)} notes with 384-dim embeddings.")
        cur.execute("SELECT extversion FROM pg_extension WHERE extname='vector'"); print("pgvector", cur.fetchone()[0])
        cur.execute("SELECT extversion FROM pg_extension WHERE extname='vectorscale'"); print("pgvectorscale", cur.fetchone()[0])
        for q, sql, label in QUERIES:
            (qv,) = emb([q])
            print(f"\n=== \"{q}\"  [{label}]")
            # Similarity search joined back to the time series: what was the temperature that hour?
            cur.execute(sql, (qv, qv))
            for t, name, sim, note, mt in cur.fetchall():
                print(f"  {t:%b %d %H:%M} UTC | {clean(name):<10} | sim {sim} | hour max {mt if mt is not None else '-'} C | {clean(note)}")
        cur.execute("SET enable_seqscan = off")
        (qv,) = emb(["air conditioner failure"])
        cur.execute("EXPLAIN SELECT note FROM maintenance_notes ORDER BY embedding <=> %s::vector LIMIT 3", (qv,))
        print("\nQuery plan (seqscan disabled to show the index):")
        for (line,) in cur.fetchall(): print("  " + re.sub(r"'\[[^\]]*\]'", "'[...384 floats...]'", line))


if __name__ == "__main__":
    main()
