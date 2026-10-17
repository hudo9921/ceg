#!/usr/bin/env bash
set -e

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

echo "🗄️ Aplicando migrações do banco de dados..."
python manage.py migrate --noinput

echo "👤 Inicializando superusuário..."
python manage.py initadmin || true



echo "🚀 Iniciando Gunicorn com 4 workers e 4 threads (24GB RAM)..."
exec gunicorn ceg_project.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 4 \
    --threads 4 \
    --worker-class gthread \
    --max-requests 1000 \
    --timeout 60
