-- pgvector + pgvectorscale on the same Tiger Cloud service as Sensor Pulse.
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS vectorscale CASCADE;

-- Free-text maintenance notes written by staff, stored next to the sensor time series.
-- A hypertable, so notes are chunked by time just like the readings.
CREATE TABLE IF NOT EXISTS maintenance_notes (
    time       TIMESTAMPTZ NOT NULL,
    sensor_id  INTEGER     NOT NULL,
    author     TEXT        NOT NULL,
    note       TEXT        NOT NULL,
    embedding  VECTOR(384) NOT NULL   -- BAAI/bge-small-en-v1.5, normalized
) WITH (tsdb.hypertable, tsdb.partition_column = 'time', tsdb.chunk_interval = '7 days');

-- StreamingDiskANN index from pgvectorscale for approximate cosine search.
CREATE INDEX IF NOT EXISTS maintenance_notes_embedding_idx
    ON maintenance_notes USING diskann (embedding vector_cosine_ops);
