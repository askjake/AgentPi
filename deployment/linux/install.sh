#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib.sh
source "$SCRIPT_DIR/lib.sh"
ROOT="$(repo_root)"
cd "$ROOT"

NON_INTERACTIVE=0
NO_START=0
SKIP_TESTS=0
for arg in "$@"; do
  case "$arg" in
    --non-interactive) NON_INTERACTIVE=1 ;;
    --no-start) NO_START=1 ;;
    --skip-tests) SKIP_TESTS=1 ;;
    *) echo "Unknown option: $arg" >&2; exit 2 ;;
  esac
done

install_packages() {
  if command -v apt-get >/dev/null 2>&1; then
    run_root apt-get update
    run_root apt-get install -y git curl openssl build-essential libpq-dev postgresql postgresql-contrib
    if ! command -v python3.13 >/dev/null 2>&1; then
      run_root apt-get install -y python3.13 python3.13-venv python3.13-dev || true
    fi
  else
    echo "Automatic package installation supports apt-based Linux only." >&2
    echo "Install Git, curl, OpenSSL, Python 3.13, PostgreSQL, build tools and libpq headers, then rerun." >&2
    return 1
  fi
}

for cmd in git curl openssl; do
  command -v "$cmd" >/dev/null 2>&1 || install_packages
done
command -v python3.13 >/dev/null 2>&1 || install_packages
if ! PYTHON_BIN="$(resolve_python313)"; then
  echo "Python 3.13 not found in system packages; bootstrapping uv for the current user..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
  export PATH="$HOME/.local/bin:$PATH"
  PYTHON_BIN="$(resolve_python313)" || {
    echo "Python 3.13 could not be installed." >&2
    exit 10
  }
fi
export PYTHON_BIN
command -v psql >/dev/null 2>&1 || install_packages
command -v psql >/dev/null 2>&1 || {
  echo "PostgreSQL client/server packages are required." >&2
  exit 11
}

mkdir -p runtime/logs runtime/workspaces runtime/backups

"$PYTHON_BIN" -m venv .venv
.venv/bin/python -m pip install --upgrade pip setuptools wheel
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pip check

"$PYTHON_BIN" -m venv dish-chat/backend/.venv
dish-chat/backend/.venv/bin/python -m pip install --upgrade pip setuptools wheel

# Exact qualified DishChat freeze, minus Windows-only pywin32.
"$PYTHON_BIN" - <<'PY'
from pathlib import Path
src = Path("deployment/evidence/requirements-dishchat-windows-freeze.txt")
dst = Path("runtime/requirements-dishchat-linux.txt")
lines = src.read_text(encoding="utf-8-sig").replace("\r\n", "\n").splitlines()
lines = [line for line in lines if line and not line.lower().startswith("pywin32==")]
dst.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

dish-chat/backend/.venv/bin/python -m pip install -r runtime/requirements-dishchat-linux.txt
dish-chat/backend/.venv/bin/python -m pip check

ENV_FILE="dish-chat/backend/.env"
touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

TOKEN="${COVERITY_ASSIST_TOKEN:-}"
if [[ -z "$TOKEN" ]]; then
  TOKEN="$(dotenv_get "$ENV_FILE" COVERITY_ASSIST_TOKEN || true)"
fi
if [[ -z "$TOKEN" && "$NON_INTERACTIVE" -eq 0 ]]; then
  read -rsp "Coverity Assist token: " TOKEN
  echo
fi
if [[ -z "$TOKEN" ]]; then
  echo "COVERITY_ASSIST_TOKEN is required." >&2
  exit 12
fi

DBPW="$(dotenv_get "$ENV_FILE" POSTGRES_PWD || true)"
[[ -n "$DBPW" ]] || DBPW="$(openssl rand -hex 24)"
MASTER_KEY="$(dotenv_get "$ENV_FILE" MASTER_KEY || true)"
if [[ -z "$MASTER_KEY" ]]; then
  MASTER_KEY="$("$PYTHON_BIN" - <<'PY'
import base64, secrets
print(base64.b64encode(secrets.token_bytes(32)).decode())
PY
)"
fi

set_env_value "$ENV_FILE" AUTH_DISABLED true 1
set_env_value "$ENV_FILE" LOCAL true 1
set_env_value "$ENV_FILE" DEBUG false 1
set_env_value "$ENV_FILE" DEFAULT_USER_EMAIL local@localhost 1
set_env_value "$ENV_FILE" POSTGRES_HOST 127.0.0.1 1
set_env_value "$ENV_FILE" POSTGRES_PORT 5432 1
set_env_value "$ENV_FILE" POSTGRES_DB dishchat_local 1
set_env_value "$ENV_FILE" POSTGRES_USER agentpi_local 1
set_env_value "$ENV_FILE" POSTGRES_PWD "$DBPW"
set_env_value "$ENV_FILE" PLLM_PROVIDER coverity-assist 1
set_env_value "$ENV_FILE" ELLM_PROVIDER coverity-assist 1
set_env_value "$ENV_FILE" COVERITY_ASSIST_URL https://coverity-assist-stg.dishtv.technology/chat 1
set_env_value "$ENV_FILE" COVERITY_ASSIST_TOKEN "$TOKEN"
set_env_value "$ENV_FILE" COVERITY_ASSIST_VERIFY_SSL false 1
set_env_value "$ENV_FILE" DEFAULT_MODEL_PREFERENCE reasoning 1
set_env_value "$ENV_FILE" ENABLE_TOOL_CALLS true 1
set_env_value "$ENV_FILE" MAX_TOOL_ITERATIONS 100 1
set_env_value "$ENV_FILE" TOOL_CALL_TIMEOUT 12000 1
set_env_value "$ENV_FILE" ENABLE_BETAREPORT_MCP false 1
set_env_value "$ENV_FILE" ENABLE_VIEWERSHIP_MCP false 1
set_env_value "$ENV_FILE" ENABLE_LOG_ASSIST_MCP false 1
set_env_value "$ENV_FILE" ENABLE_INTERNAL_TOOLS_MCP false 1
set_env_value "$ENV_FILE" MASTER_KEY "$MASTER_KEY"

ensure_postgres_running
DB_NAME="$(dotenv_get "$ENV_FILE" POSTGRES_DB)"
DB_USER="$(dotenv_get "$ENV_FILE" POSTGRES_USER)"
DB_PW="$(dotenv_get "$ENV_FILE" POSTGRES_PWD)"

as_postgres psql -v ON_ERROR_STOP=1 -v db_user="$DB_USER" -v db_pw="$DB_PW" <<'SQL'
SELECT format(
  'CREATE ROLE %I LOGIN PASSWORD %L',
  :'db_user', :'db_pw'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'db_user') \gexec
SELECT format(
  'ALTER ROLE %I WITH LOGIN PASSWORD %L',
  :'db_user', :'db_pw'
) \gexec
SQL

if ! as_postgres psql -tAc "SELECT 1 FROM pg_database WHERE datname='$DB_NAME'" | grep -q 1; then
  as_postgres createdb -O "$DB_USER" "$DB_NAME"
fi
as_postgres psql -d "$DB_NAME" -v ON_ERROR_STOP=1 -c 'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'

export POSTGRES_HOST="$(dotenv_get "$ENV_FILE" POSTGRES_HOST)"
export POSTGRES_PORT="$(dotenv_get "$ENV_FILE" POSTGRES_PORT)"
export POSTGRES_DB="$DB_NAME"
export POSTGRES_USER="$DB_USER"
export POSTGRES_PWD="$DB_PW"

(
  cd dish-chat/backend/app
  PYTHONPATH="$(cd .. && pwd)" ../.venv/bin/python -m alembic -c alembic.ini upgrade head
  PYTHONPATH="$(cd .. && pwd)" ../.venv/bin/python -m alembic -c alembic.ini current
)

unset POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PWD DBPW DB_PW TOKEN MASTER_KEY

if [[ "$SKIP_TESTS" -eq 0 ]]; then
  .venv/bin/python -m pytest -q
  (
    cd dish-chat/backend
    PYTHONPATH="$PWD" .venv/bin/python -m pytest -q tests_windows
  )
fi

if [[ "$NO_START" -eq 0 ]]; then
  bash "$SCRIPT_DIR/start.sh"
fi

echo "============================================================"
echo "AGENTPI001 LINUX INSTALL PASS"
echo "Repo:      $ROOT"
echo "DishChat:  http://127.0.0.1:3000/"
echo "Backend:   http://127.0.0.1:8000/api/docs"
echo "AgentPi:   http://127.0.0.1:8765/"
echo "Postgres:  127.0.0.1:5432"
echo "============================================================"
