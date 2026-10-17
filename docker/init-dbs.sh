#!/usr/bin/env bash
set -e

echo "🔧 [Postgres Init] Configurando banco secundário para a Evolution API..."

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<-EOSQL
    SELECT 'CREATE DATABASE evolution'
    WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'evolution')\gexec
    GRANT ALL PRIVILEGES ON DATABASE evolution TO $POSTGRES_USER;
EOSQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "evolution" <<-EOSQL
    GRANT ALL ON SCHEMA public TO $POSTGRES_USER;
EOSQL

echo "✅ [Postgres Init] Bancos '$POSTGRES_DB' e 'evolution' prontos e autorizados para '$POSTGRES_USER'!"
