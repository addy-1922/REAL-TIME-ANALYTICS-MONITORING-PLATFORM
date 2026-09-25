FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    HOME=/home/app

WORKDIR /app

RUN groupadd --system app && useradd --system --gid app --create-home --home-dir /home/app --shell /usr/sbin/nologin app

COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

COPY --chown=app:app . .

# /app itself is created by WORKDIR and stays owned by root, and .dockerignore
# keeps staticfiles out of the build context, so collectstatic running as the
# unprivileged app user cannot create STATIC_ROOT. Create and hand it over
# while still root.
RUN mkdir -p /app/staticfiles && chown -R app:app /app/staticfiles

USER app
RUN python manage.py collectstatic --noinput

EXPOSE 8000
STOPSIGNAL SIGTERM

CMD ["python", "-m", "uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", "--proxy-headers", "--forwarded-allow-ips=*"]
