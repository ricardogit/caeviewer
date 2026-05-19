#!/bin/bash
set -e

# Wait for PostgreSQL
if [ -n "$DATABASE_URL" ]; then
    DB_HOST=$(echo "$DATABASE_URL" | sed -E 's|.*@([^:/]+).*|\1|')
    DB_PORT=$(echo "$DATABASE_URL" | sed -nE 's|.*:([0-9]+)/[^/].*|\1|p')
    DB_PORT=${DB_PORT:-5432}
    echo "[entrypoint] Waiting for PostgreSQL at $DB_HOST:$DB_PORT ..."
    until nc -z "$DB_HOST" "$DB_PORT"; do
        sleep 1
    done
    echo "[entrypoint] PostgreSQL is ready."
fi

exec "$@"
