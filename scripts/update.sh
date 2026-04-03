#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

require_file "$ROOT_DIR/$ENV_FILE"
require_clean_worktree

branch="${1:-}"
if [[ -n "$branch" ]]; then
  git -C "$ROOT_DIR" checkout "$branch"
fi

git -C "$ROOT_DIR" fetch --all --tags
current_branch="$(git -C "$ROOT_DIR" rev-parse --abbrev-ref HEAD)"
git -C "$ROOT_DIR" pull --ff-only origin "$current_branch"

"$ROOT_DIR/scripts/backup.sh"
compose build backend celery celery-beat frontend
compose run --rm backend alembic upgrade head
compose up -d backend celery celery-beat frontend nginx

echo "Update complete on branch $current_branch"
git -C "$ROOT_DIR" rev-parse HEAD

