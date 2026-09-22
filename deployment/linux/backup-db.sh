#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
ROOT="$(repo_root)"
cd "$ROOT"
ensure_postgres_running

ENV_FILE="dish-chat/backend/.env"
DB_HOST="$(dotenv_get "$ENV_FILE" POSTGRES_HOST)"
DB_PORT="$(dotenv_get "$ENV_FILE" POSTGRES_PORT)"
DB_NAME="$(dotenv_get "$ENV_FILE" POSTGRES_DB)"
DB_USER="$(dotenv_get "$ENV_FILE" POSTGRES_USER)"
DB_PW="$(dotenv_get "$ENV_FILE" POSTGRES_PWD)"

mkdir -p runtime/backups
OUT="${1:-runtime/backups/dishchat-$(date -u +%Y%m%dT%H%M%SZ).dump}"
PGPASSWORD="$DB_PW" pg_dump -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -Fc -f "$OUT"
[[ -s "$OUT" ]] || { echo "Backup is empty." >&2; exit 20; }
echo "DB_BACKUP=$OUT"
