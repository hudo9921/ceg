#!/usr/bin/env bash
# ==============================================================================
# Deploy no servidor (Oracle Cloud). Executado pelo GitHub Actions após o `git reset`
# para a main. Variáveis opcionais vindas dos secrets: FIELD_ENCRYPTION_KEY, BACKUP_PASSPHRASE.
#
# Ordem: completa o .env -> backup -> build -> (rotação única da senha do Postgres)
#        -> sobe os containers -> confere /health/ -> instala o cron.
# Se algo falhar antes do `up`, a versão anterior continua no ar.
# ==============================================================================
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

APP_DIR="$(pwd)"
BACKUP_DIR="${BACKUP_DIR:-/home/ubuntu/ceg-backups}"
LEGACY_PG_PASSWORD="valcegs_secure_password_2026"  # antigo default do compose (público no git)

touch .env && chmod 600 .env

# --- 1. .env: só ADICIONA o que falta; nunca sobrescreve um valor existente --------
ensure_var() {
    if ! grep -q "^$1=." .env; then
        sed -i "/^$1=\s*$/d" .env
        printf '%s=%s\n' "$1" "$2" >> .env
        echo "[env] $1 adicionada ao .env"
    fi
}
# Senha com que o volume do Postgres foi inicializado (rotacionada no passo 4).
ensure_var POSTGRES_PASSWORD "$LEGACY_PG_PASSWORD"
ensure_var SECRET_KEY "$(openssl rand -hex 48)"
[ -n "${FIELD_ENCRYPTION_KEY:-}" ] && ensure_var FIELD_ENCRYPTION_KEY "$FIELD_ENCRYPTION_KEY"
[ -n "${BACKUP_PASSPHRASE:-}" ] && ensure_var BACKUP_PASSPHRASE "$BACKUP_PASSPHRASE"
# Produção nunca roda com DEBUG ligado.
sed -i 's/^DEBUG=.*/DEBUG=False/' .env
# A porta 8080 da Evolution só escuta em localhost: o Django usa a rede interna do Docker.
sed -i -E 's#^EVOLUTION_API_URL=https?://(localhost|127\.0\.0\.1|150\.136\.166\.17)(:8080)?/?$#EVOLUTION_API_URL=http://valcegs-evolution:8080#' .env

for var in SECRET_KEY POSTGRES_PASSWORD FIELD_ENCRYPTION_KEY; do
    grep -q "^${var}=." .env || { echo "ERRO: defina ${var} no .env do servidor"; exit 1; }
done

# --- 2. Backup antes de qualquer mudança ------------------------------------------
BACKUP_DIR="$BACKUP_DIR" bash scripts/backup_database.sh

# --- 3. Build (a versão atual segue no ar enquanto isso) ---------------------------
chmod +x entrypoint.sh scripts/*.sh || true
docker compose build

# --- 4. Rotação única da senha padrão do Postgres ---------------------------------
if grep -q "^POSTGRES_PASSWORD=${LEGACY_PG_PASSWORD}$" .env \
        && docker ps --format '{{.Names}}' | grep -qx valcegs-db; then
    PG_USER="$(grep -E '^POSTGRES_USER=' .env | tail -n1 | cut -d= -f2- | tr -d '\r')"
    PG_USER="${PG_USER:-valcegs}"
    NEW_PG_PASSWORD="$(openssl rand -hex 24)"
    # Prepara o novo .env antes de alterar o banco (troca todas as ocorrências, ex.: URIs).
    sed "s/${LEGACY_PG_PASSWORD}/${NEW_PG_PASSWORD}/g" .env > .env.new && chmod 600 .env.new
    # Conexão local do container usa autenticação "trust": a senha antiga não é necessária.
    docker exec valcegs-db psql -v ON_ERROR_STOP=1 -q -U "$PG_USER" -d postgres \
        -c "ALTER USER \"${PG_USER}\" WITH PASSWORD '${NEW_PG_PASSWORD}';" >/dev/null
    mv .env.new .env
    echo "[env] senha padrão do Postgres substituída por uma aleatória"
fi

# --- 5. Sobe a nova versão e confere a saúde (app + banco) -------------------------
docker compose up -d
healthy=""
for _ in $(seq 1 36); do
    if curl -fsS -o /dev/null --max-time 5 http://127.0.0.1:8000/health/; then
        healthy=1
        break
    fi
    sleep 5
done
if [ -z "$healthy" ]; then
    echo "ERRO: /health/ não respondeu após 3 minutos. Últimos logs do web:"
    docker compose logs --tail 80 ceg-web || true
    exit 1
fi
echo "✅ Aplicação saudável"
docker image prune -f >/dev/null

# --- 6. Rotinas diárias (idempotente: substitui só as linhas marcadas) -------------
CRON_TAG="# ceg-managed"
{
    crontab -l 2>/dev/null | grep -v "$CRON_TAG" || true
    echo "0 3 * * * cd $APP_DIR && BACKUP_DIR=$BACKUP_DIR bash scripts/backup_database.sh >> $HOME/backup.log 2>&1 $CRON_TAG"
    echo "30 3 * * * docker exec valcegs-web python manage.py purge_personal_data >> $HOME/purge.log 2>&1 $CRON_TAG"
} | crontab -
echo "✅ Cron de backup e retenção de dados instalado"
