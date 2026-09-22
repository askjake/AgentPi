#!/usr/bin/env bash

repo_root() {
  cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd
}

dotenv_get() {
  local file="$1" key="$2"
  [[ -f "$file" ]] || return 1
  awk -v key="$key" '
    index($0, key "=") == 1 {
      sub("^[^=]*=", "", $0)
      print
      exit
    }
  ' "$file"
}

set_env_value() {
  local file="$1" key="$2" value="$3" only_if_missing="${4:-0}"
  "${PYTHON_BIN:-python3.13}" - "$file" "$key" "$value" "$only_if_missing" <<'PY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
key, value, only = sys.argv[2], sys.argv[3], sys.argv[4] == "1"
lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
out = []
found = False
for line in lines:
    if line.startswith(key + "="):
        found = True
        out.append(line if only else f"{key}={value}")
    else:
        out.append(line)
if not found:
    out.append(f"{key}={value}")
path.write_text("\n".join(out) + "\n", encoding="utf-8")
PY
}

run_root() {
  if [[ "$EUID" -eq 0 ]]; then
    "$@"
  else
    command -v sudo >/dev/null 2>&1 || {
      echo "sudo is required for this operation." >&2
      return 1
    }
    sudo "$@"
  fi
}

as_postgres() {
  if [[ "$EUID" -eq 0 ]]; then
    command -v runuser >/dev/null 2>&1 || {
      echo "runuser is required when running installer as root." >&2
      return 1
    }
    runuser -u postgres -- "$@"
  else
    command -v sudo >/dev/null 2>&1 || {
      echo "sudo is required to run PostgreSQL administration commands." >&2
      return 1
    }
    sudo -u postgres "$@"
  fi
}

ensure_postgres_running() {
  if command -v systemctl >/dev/null 2>&1; then
    run_root systemctl enable --now postgresql >/dev/null
  elif command -v service >/dev/null 2>&1; then
    run_root service postgresql start
  else
    echo "Unable to start PostgreSQL automatically." >&2
    return 1
  fi
}

wait_http() {
  local name="$1" url="$2" attempts="${3:-30}"
  local i
  for ((i=0; i<attempts; i++)); do
    if curl -fsS "$url" >/dev/null 2>&1; then
      printf 'PASS %-18s %s\n' "$name" "$url"
      return 0
    fi
    sleep 1
  done
  echo "FAIL $name $url" >&2
  return 1
}

resolve_python313() {
  if command -v python3.13 >/dev/null 2>&1; then
    command -v python3.13
    return 0
  fi
  if command -v uv >/dev/null 2>&1; then
    uv python install 3.13 >/dev/null
    uv python find 3.13
    return 0
  fi
  if [[ -x "$HOME/.local/bin/uv" ]]; then
    "$HOME/.local/bin/uv" python install 3.13 >/dev/null
    "$HOME/.local/bin/uv" python find 3.13
    return 0
  fi
  return 1
}
