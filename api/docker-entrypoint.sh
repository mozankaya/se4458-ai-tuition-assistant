#!/bin/sh
# Optionally create the schema and load demo data, then start the API.
# SEED_ON_START=true is idempotent: missing tables and demo rows are created, existing data is kept.
set -eu

if [ "${SEED_ON_START:-false}" = "true" ]; then
    python -m app.seed
fi

exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT:-8080}"
