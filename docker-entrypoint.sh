#!/bin/sh
set -eu

echo "=== Analytics Platform container starting ==="
echo "Python version:"
python --version
echo "Working directory:"
pwd
echo "PORT=${PORT:-8000}"

echo "=== Running Django system checks ==="
python manage.py check --deploy

echo "=== Running database migrations ==="
python manage.py migrate --noinput

echo "=== Starting Uvicorn ==="
exec python -m uvicorn config.asgi:application --host 0.0.0.0 --port "${PORT:-8000}"
