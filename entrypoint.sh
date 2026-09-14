#!/usr/bin/env bash
set -e

echo "🗄️ Aplicando migrações do banco de dados..."
python manage.py migrate --noinput

echo "👤 Inicializando superusuário..."
python manage.py initadmin || true

echo "📋 Verificando CEGs no banco de dados..."
python manage.py import_new_cegs --only-if-empty || true

echo "🚀 Iniciando Gunicorn com 4 workers e 4 threads (24GB RAM)..."
exec gunicorn ceg_project.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers 4 \
    --threads 4 \
    --worker-class gthread \
    --max-requests 1000 \
    --timeout 60
