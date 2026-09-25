#!/bin/sh
set -e

echo "Running Django database migrations..."
python manage.py migrate --noinput

echo "Starting Uvicorn..."
exec python -m uvicorn config.asgi:application --host 0.0.0.0 --port "${PORT:-8000}"
