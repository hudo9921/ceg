#!/usr/bin/env bash
# ==============================================================================
# Script de Backup Automático Diário do PostgreSQL (Oracle Cloud VM)
#
# Os dumps contêm dados pessoais (LGPD). Com BACKUP_PASSPHRASE definida (no ambiente
# ou no .env do projeto), cada dump é criptografado com AES-256 (openssl, PBKDF2).
#
# Restaurar um backup criptografado:
#   openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass env:BACKUP_PASSPHRASE \
#       -in valcegs_db_XXXX.sql.gz.enc | gunzip | docker exec -i valcegs-db psql -U valcegs -d valcegs_db
# ==============================================================================
set -eo pipefail

BACKUP_DIR="${BACKUP_DIR:-/app/backups}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
mkdir -p "$BACKUP_DIR"
chmod 700 "$BACKUP_DIR" || true

# Lê BACKUP_PASSPHRASE do .env do projeto se não vier do ambiente.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ -z "${BACKUP_PASSPHRASE:-}" ] && [ -f "$SCRIPT_DIR/../.env" ]; then
    BACKUP_PASSPHRASE="$(grep -E '^BACKUP_PASSPHRASE=' "$SCRIPT_DIR/../.env" | tail -n1 | cut -d= -f2- | tr -d '\r' || true)"
fi
export BACKUP_PASSPHRASE

# Primeiro deploy (banco ainda não existe): nada a salvar, não bloqueia o deploy.
if ! docker ps --format '{{.Names}}' | grep -qx valcegs-db; then
    echo "⚠️ [Backup] Container valcegs-db não está rodando — backup ignorado."
    exit 0
fi

dump_db() {
    local db="$1" out="$BACKUP_DIR/${1}_${TIMESTAMP}.sql.gz"
    if [ -n "$BACKUP_PASSPHRASE" ]; then
        docker exec valcegs-db pg_dump -U valcegs -d "$db" | gzip \
            | openssl enc -aes-256-cbc -pbkdf2 -iter 200000 -salt -pass env:BACKUP_PASSPHRASE -out "${out}.enc"
        out="${out}.enc"
    else
        docker exec valcegs-db pg_dump -U valcegs -d "$db" | gzip > "$out"
    fi
    chmod 600 "$out"
    echo "   - $out"
}

echo "📦 [Backup] Iniciando backup do PostgreSQL..."
if [ -z "$BACKUP_PASSPHRASE" ]; then
    echo "⚠️ [Backup] BACKUP_PASSPHRASE não definida — dumps salvos SEM criptografia."
fi

dump_db valcegs_db
dump_db evolution
echo "✅ [Backup] Backup concluído em $BACKUP_DIR"

# Mantém apenas os últimos 7 dias de backup local para economizar espaço
find "$BACKUP_DIR" \( -name "*.sql.gz" -o -name "*.sql.gz.enc" \) -type f -mtime +7 -delete
echo "🧹 [Backup] Backups com mais de 7 dias removidos automaticamente."
