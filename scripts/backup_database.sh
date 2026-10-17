#!/usr/bin/env bash
# ==============================================================================
# Script de Backup Automático Diário do PostgreSQL (Oracle Cloud VM)
# ==============================================================================
set -e

BACKUP_DIR="/app/backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
mkdir -p "$BACKUP_DIR"

echo "📦 [Backup] Iniciando backup diário do PostgreSQL..."

# Dump do Django
docker exec valcegs-db pg_dump -U valcegs -d valcegs_db | gzip > "$BACKUP_DIR/valcegs_db_${TIMESTAMP}.sql.gz"

# Dump da Evolution API
docker exec valcegs-db pg_dump -U valcegs -d evolution | gzip > "$BACKUP_DIR/evolution_${TIMESTAMP}.sql.gz"

echo "✅ [Backup] Backup concluído em $BACKUP_DIR:"
echo "   - $BACKUP_DIR/valcegs_db_${TIMESTAMP}.sql.gz"
echo "   - $BACKUP_DIR/evolution_${TIMESTAMP}.sql.gz"

# Mantém apenas os últimos 7 dias de backup local para economizar espaço
find "$BACKUP_DIR" -name "*.sql.gz" -type f -mtime +7 -delete
echo "🧹 [Backup] Backups com mais de 7 dias removidos automaticamente."
