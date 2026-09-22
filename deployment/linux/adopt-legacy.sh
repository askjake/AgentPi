#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
ROOT="$(repo_root)"
cd "$ROOT"

LEGACY="${1:-$HOME/dish-chat}"
[[ -d "$LEGACY/backend" ]] || { echo "Legacy DishChat backend not found: $LEGACY/backend" >&2; exit 2; }
[[ -f "$LEGACY/backend/.env" ]] || { echo "Legacy backend .env not found: $LEGACY/backend/.env" >&2; exit 3; }
[[ "$LEGACY" != "$ROOT/dish-chat" ]] || { echo "Legacy path already points at repo-native tree." >&2; exit 4; }

if [[ -f dish-chat/backend/.env ]]; then
  echo "Repo-native backend .env already exists; refusing to overwrite it." >&2
  exit 5
fi

# Preserve a source backup of the legacy live tree, excluding its venv/logs.
mkdir -p runtime/backups
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
tar --exclude='./backend/.venv' --exclude='./logs' \
  -C "$(dirname "$LEGACY")" -czf "runtime/backups/legacy-dish-chat-$STAMP.tar.gz" "$(basename "$LEGACY")"

# Stop known legacy systemd services if present.
if command -v systemctl >/dev/null 2>&1; then
  if systemctl list-unit-files dishchat-backend.service >/dev/null 2>&1; then
    run_root systemctl stop dishchat-backend.service || true
  fi
  if systemctl list-unit-files dishchat-frontend.service >/dev/null 2>&1; then
    run_root systemctl stop dishchat-frontend.service || true
  fi
fi

# Copy runtime configuration only. The system PostgreSQL database itself remains in place.
cp "$LEGACY/backend/.env" dish-chat/backend/.env
chmod 600 dish-chat/backend/.env
for rel in .env backend/app/.env backend/.env.local; do
  if [[ -f "$LEGACY/$rel" ]]; then
    mkdir -p "$(dirname "dish-chat/$rel")"
    cp "$LEGACY/$rel" "dish-chat/$rel"
  fi
done

# Back up the existing DB using the copied environment before running migrations.
# install.sh will preserve existing DB coordinates/passwords and ensure the role/schema are ready.
bash "$SCRIPT_DIR/install.sh" --non-interactive --no-start --skip-tests
bash "$SCRIPT_DIR/backup-db.sh"
bash "$SCRIPT_DIR/start.sh"
bash "$SCRIPT_DIR/verify.sh"

echo "LEGACY_ROOT=$LEGACY"
echo "NEW_ROOT=$ROOT"
echo "Legacy source and systemd units were preserved/stopped. Remove them only after validation."
echo "AGENTPI001 LINUX LEGACY ADOPTION PASS"
