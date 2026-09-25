#!/bin/sh
set -eu

echo "=== Analytics Platform container starting ==="
echo "Python version:"
python --version
echo "Working directory:"
pwd
echo "PORT=${PORT:-8000}"

echo "=== Running Django database migrations ==="

# One-time recovery for the new Render PostgreSQL database. It is opt-in: without
# RESET_RENDER_DATABASE=true the entrypoint only migrates. The recovery command
# also refuses to reset anything unless the recorded migration history is
# actually inconsistent, so leaving the variable set is harmless after the first
# successful reset.
reset_render_database="$(printf '%s' "${RESET_RENDER_DATABASE:-}" | tr '[:upper:]' '[:lower:]' | tr -d '[:space:]')"
if [ "$reset_render_database" = "true" ]; then
    echo "=== RESET_RENDER_DATABASE=true: running one-time database recovery ==="
    python manage.py reset_render_database
fi

python manage.py migrate --noinput

echo "=== Starting Uvicorn ==="
exec python -m uvicorn config.asgi:application --host 0.0.0.0 --port "${PORT:-8000}"
