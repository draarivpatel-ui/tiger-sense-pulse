#!/usr/bin/env bash
# Usage: DATABASE_URL="postgres://tsdbadmin:...@xxxx.tsdb.cloud.timescale.com:3xxxx/tsdb?sslmode=require" ./run.sh
# Builds the schema, simulates data, creates the continuous aggregates, then runs the demo queries.
set -euo pipefail
: "${DATABASE_URL:?Set DATABASE_URL to your Tiger Cloud service connection string}"
cd "$(dirname "$0")"
for f in sql/01_schema.sql sql/02_simulate.sql sql/03_continuous_aggregates.sql sql/04_queries.sql; do
  echo "==> $f"
  psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -q -f "$f"
done
