#!/usr/bin/env bash
# Script de Build do Render.com para CEGManager
set -o errexit

echo "📦 Instalando dependências..."
pip install --upgrade pip
pip install -r requirements.txt

echo "🎨 Coletando arquivos estáticos (WhiteNoise)..."
python manage.py collectstatic --no-input

echo "🗄️ Aplicando migrações do banco de dados..."
python manage.py migrate

echo "👤 Inicializando superusuário (se configurado em ADMIN_PASSWORD)..."
python manage.py initadmin

echo "✅ Build concluído com sucesso!"
