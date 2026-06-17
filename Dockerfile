# Fighter Bull's Student Portal — production image
FROM python:3.13-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# System libs for Pillow runtime (image fields) — psycopg[binary] bundles libpq.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libjpeg62-turbo zlib1g \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first (better layer caching)
COPY requirements.txt .
RUN pip install -r requirements.txt

# App code
COPY . .

# Make entrypoint executable and strip any CRLF (Windows checkouts)
RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Non-root user
RUN useradd -m appuser && mkdir -p /app/media /app/staticfiles /app/secrets \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/entrypoint.sh"]
# --timeout 3600: allow long large-file (multi-GB) uploads without the worker
# being killed mid-transfer.
CMD ["gunicorn", "config.wsgi:application", "--bind", "0.0.0.0:8000", \
     "--workers", "3", "--timeout", "3600"]
