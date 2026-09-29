#!/usr/bin/env bash
# Copy the VPS (primary) Postgres database into the Railway (backup) Postgres.
#
# ONE-WAY: VPS -> Railway. Everything in the Railway database is replaced.
# Run this on the VPS, e.g. hourly from cron:
#   0 * * * * /path/to/SMARTTT_BACKEND/scripts/sync_db_to_railway.sh >> /var/log/smarttt_railway_sync.log 2>&1
#
# Needs RAILWAY_DATABASE_URL: the Railway Postgres "DATABASE_PUBLIC_URL"
# (Railway -> Postgres service -> Variables). Put it in the .env file next to
# docker-compose.prod.yml, or export it before running.
set -euo pipefail

cd "$(dirname "$0")/.."

if [ -z "${RAILWAY_DATABASE_URL:-}" ] && [ -f .env ]; then
    RAILWAY_DATABASE_URL="$(grep -E '^RAILWAY_DATABASE_URL=' .env | cut -d= -f2- || true)"
fi
: "${RAILWAY_DATABASE_URL:?RAILWAY_DATABASE_URL is not set}"

DB_CONTAINER="${DB_CONTAINER:-smarttt_prod_db}"
PG_IMAGE="${PG_IMAGE:-postgres:15-alpine}"
DUMP_FILE="$(mktemp /tmp/smarttt_dump.XXXXXX)"
trap 'rm -f "$DUMP_FILE"' EXIT

# Never run two syncs at once
exec 9>/tmp/smarttt_railway_sync.lock
flock -n 9 || { echo "$(date -Is) another sync is running, skipping"; exit 0; }

echo "$(date -Is) dumping VPS database from $DB_CONTAINER..."
docker exec "$DB_CONTAINER" sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc --no-owner --no-acl' > "$DUMP_FILE"

if [ ! -s "$DUMP_FILE" ]; then
    echo "$(date -Is) dump is empty, aborting (Railway left untouched)"
    exit 1
fi

echo "$(date -Is) restoring into Railway ($(du -h "$DUMP_FILE" | cut -f1))..."
# --single-transaction: if anything fails, Railway keeps its previous copy
docker run --rm -i "$PG_IMAGE" \
    pg_restore --clean --if-exists --no-owner --no-acl --single-transaction \
    -d "$RAILWAY_DATABASE_URL" < "$DUMP_FILE"

echo "$(date -Is) sync complete"
