#!/usr/bin/env bash
# exit on error
set -o errexit

export DJANGO_SETTINGS_MODULE=config.settings.production

# Collect static files
python manage.py collectstatic --noinput

# Run database migrations
python manage.py migrate --noinput

# Start Gunicorn
exec gunicorn config.wsgi:application \
  --bind "0.0.0.0:${PORT:-8000}" \
  --workers 2 \
  --timeout 120 \
  --access-logfile - \
  --error-logfile -