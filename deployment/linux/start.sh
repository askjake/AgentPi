#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
ROOT="$(repo_root)"
cd "$ROOT"

ensure_postgres_running
mkdir -p runtime/logs runtime/workspaces

start_pid() {
  local name="$1"; shift
  local pidfile="runtime/${name}.pid"
  if [[ -f "$pidfile" ]]; then
    local old
    old="$(cat "$pidfile" 2>/dev/null || true)"
    if [[ -n "$old" ]] && kill -0 "$old" 2>/dev/null; then
      echo "$name already running as PID $old"
      return
    fi
    rm -f "$pidfile"
  fi
  "$@" >"runtime/logs/${name}.out.log" 2>"runtime/logs/${name}.err.log" &
  echo $! > "$pidfile"
  echo "$name PID: $!"
}

if ! curl -fsS http://127.0.0.1:8765/rest/api/v1/health >/dev/null 2>&1; then
  start_pid agentpi env AGENTPI_HOST=127.0.0.1 AGENTPI_PORT=8765 .venv/bin/python -m backend
else
  echo "Reusing healthy AgentPi on :8765"
fi

if ! curl -fsS http://127.0.0.1:8000/rest/api/v1/health >/dev/null 2>&1; then
  (
    cd dish-chat/backend
    nohup env \
      AGENTPI_URL=http://127.0.0.1:8765 \
      AGENT_MODE_WORKDIR="$ROOT/runtime/workspaces" \
      .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 \
      >"$ROOT/runtime/logs/dishchat-backend.out.log" \
      2>"$ROOT/runtime/logs/dishchat-backend.err.log" &
    echo $! > "$ROOT/runtime/dishchat-backend.pid"
  )
fi

if ! curl -fsS http://127.0.0.1:3000/health >/dev/null 2>&1; then
  (
    cd dish-chat/frontend
    nohup ../backend/.venv/bin/python server.py \
      >"$ROOT/runtime/logs/dishchat-frontend.out.log" \
      2>"$ROOT/runtime/logs/dishchat-frontend.err.log" &
    echo $! > "$ROOT/runtime/dishchat-frontend.pid"
  )
fi

wait_http "AgentPi" "http://127.0.0.1:8765/rest/api/v1/health" 15
wait_http "DishChat backend" "http://127.0.0.1:8000/rest/api/v1/health" 40
wait_http "DishChat frontend" "http://127.0.0.1:3000/health" 20

echo "AGENTPI001 LINUX STACK RUNNING"
