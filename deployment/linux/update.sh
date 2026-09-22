#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/lib.sh"
ROOT="$(repo_root)"
cd "$ROOT"

BRANCH="${1:-feature/agentpi-initial}"
if [[ -n "$(git status --porcelain --untracked-files=no)" ]]; then
  echo "Tracked working tree changes detected:" >&2
  git status --short
  exit 20
fi

bash "$SCRIPT_DIR/backup-db.sh"
OLD_SHA="$(git rev-parse HEAD)"
mkdir -p runtime
printf '%s\n' "$OLD_SHA" > runtime/pre-update-git-sha.txt

bash "$SCRIPT_DIR/stop.sh"

git fetch origin "$BRANCH"
git switch "$BRANCH"
git merge --ff-only "origin/$BRANCH"

bash "$SCRIPT_DIR/install.sh" --non-interactive --no-start
bash "$SCRIPT_DIR/start.sh"
bash "$SCRIPT_DIR/verify.sh"

echo "PREVIOUS_SHA=$OLD_SHA"
echo "CURRENT_SHA=$(git rev-parse HEAD)"
echo "AGENTPI001 LINUX UPDATE PASS"
