#!/bin/sh
set -e

# Wait for Postgres if configured
if [ -n "$POSTGRES_DB" ]; then
    echo "Waiting for database at ${POSTGRES_HOST:-db}:${POSTGRES_PORT:-5432}..."
    until python -c "import socket,os,sys; s=socket.socket(); s.settimeout(2); \
        s.connect((os.environ.get('POSTGRES_HOST','db'), int(os.environ.get('POSTGRES_PORT','5432')))); s.close()" 2>/dev/null; do
        sleep 1
    done
    echo "Database is up."
fi

echo "Applying migrations..."
python manage.py migrate --noinput

echo "Collecting static files..."
python manage.py collectstatic --noinput

# Optional: load demo data on first boot when SEED_DEMO=1
if [ "$SEED_DEMO" = "1" ]; then
    echo "Seeding demo data..."
    python manage.py seed_demo || true
fi

exec "$@"
