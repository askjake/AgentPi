#!/usr/bin/env bash
set -Eeuo pipefail
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
ROOT="$(repo_root)"
cd "$ROOT"

wait_http "AgentPi" "http://127.0.0.1:8765/rest/api/v1/health" 3
wait_http "DishChat backend" "http://127.0.0.1:8000/rest/api/v1/health" 3
wait_http "DishChat frontend" "http://127.0.0.1:3000/health" 3

ENV_FILE="dish-chat/backend/.env"
DB_HOST="$(dotenv_get "$ENV_FILE" POSTGRES_HOST)"
DB_PORT="$(dotenv_get "$ENV_FILE" POSTGRES_PORT)"
DB_NAME="$(dotenv_get "$ENV_FILE" POSTGRES_DB)"
DB_USER="$(dotenv_get "$ENV_FILE" POSTGRES_USER)"
DB_PW="$(dotenv_get "$ENV_FILE" POSTGRES_PWD)"

DB_STATE="$(PGPASSWORD="$DB_PW" psql -h "$DB_HOST" -p "$DB_PORT" -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -Atc \
  "SELECT (SELECT version_num FROM alembic_version LIMIT 1), (SELECT extname FROM pg_extension WHERE extname='uuid-ossp');")"
[[ "$DB_STATE" == "20260918_fix_message_role_enum|uuid-ossp" ]] || {
  echo "Unexpected database state: $DB_STATE" >&2
  exit 20
}
echo "DB_STATE=$DB_STATE"
echo "GIT_SHA=$(git rev-parse HEAD)"
echo "AGENTPI001 LINUX VERIFY PASS"
