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

echo "📋 Verificando CEGs iniciais no banco de dados..."
python manage.py shell -c "from apps.cegs.models import CEG; import subprocess, sys; subprocess.run([sys.executable, 'manage.py', 'import_new_cegs']) if not CEG.objects.exists() else print('✅ CEGs já cadastradas no banco.')"

echo "✅ Build concluído com sucesso!"
