#!/usr/bin/env bash
# exit on error
set -o errexit

# Run migrations
python manage.py migrate --noinput

# Start Gunicorn
gunicorn config.wsgi:application