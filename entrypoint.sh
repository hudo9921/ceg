#!/usr/bin/env bash
set -e

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

echo "🗄️ Aplicando migrações do banco de dados..."
python manage.py migrate --noinput

echo "👤 Inicializando superusuário..."
python manage.py initadmin || true



# Padrão para a VM E2.1.Micro (1 GB). Numa máquina maior: GUNICORN_WORKERS=4 no .env.
WORKERS="${GUNICORN_WORKERS:-2}"
THREADS="${GUNICORN_THREADS:-4}"
echo "Iniciando Gunicorn com ${WORKERS} workers e ${THREADS} threads..."
exec gunicorn ceg_project.wsgi:application \
    --bind 0.0.0.0:8000 \
    --workers "$WORKERS" \
    --threads "$THREADS" \
    --worker-class gthread \
    --max-requests 1000 \
    --timeout 60
