#!/bin/sh
set -e

# Wait for PostgreSQL to become available
if [ -n "$POSTGRES_HOST" ]; then
    echo "Waiting for PostgreSQL at $POSTGRES_HOST:${POSTGRES_PORT:-5432}..."
    while ! nc -z "$POSTGRES_HOST" "${POSTGRES_PORT:-5432}"; do
        sleep 0.5
    done
    echo "PostgreSQL is ready."
fi

# Set SKIP_SETUP=1 for one-off/cron services that share this image
if [ "$SKIP_SETUP" != "1" ]; then
    # Apply database migrations
    echo "Applying database migrations..."
    python manage.py migrate --noinput

    # Static files are collected at build time (see Dockerfile)

    # Create the admin superuser if DJANGO_SUPERUSER_EMAIL/PASSWORD are set
    python manage.py create_admin
fi

echo "Starting application with command: $@"
exec "$@"
