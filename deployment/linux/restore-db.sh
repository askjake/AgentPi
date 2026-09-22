#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
ROOT="$(repo_root)"
cd "$ROOT"

BACKUP="${1:-}"
FORCE="${2:-}"
[[ -n "$BACKUP" && -f "$BACKUP" ]] || { echo "usage: bash restore-db.sh <dump> --force" >&2; exit 2; }
[[ "$FORCE" == "--force" ]] || { echo "Restore is destructive; pass --force." >&2; exit 3; }

ensure_postgres_running
ENV_FILE="dish-chat/backend/.env"
DB_HOST="$(dotenv_get "$ENV_FILE" POSTGRES_HOST)"
DB_PORT="$(dotenv_get "$ENV_FILE" POSTGRES_PORT)"
DB_NAME="$(dotenv_get "$ENV_FILE" POSTGRES_DB)"
DB_USER="$(dotenv_get "$ENV_FILE" POSTGRES_USER)"
DB_PW="$(dotenv_get "$ENV_FILE" POSTGRES_PWD)"

as_postgres dropdb --force "$DB_NAME"
as_postgres createdb -O "$DB_USER" "$DB_NAME"
as_postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'
PGPASSWORD="$DB_PW" pg_restore -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" --no-owner "$BACKUP"
echo "DB RESTORE PASS"
