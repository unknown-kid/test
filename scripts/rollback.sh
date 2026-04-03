#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

target_ref="${1:-}"
if [[ -z "$target_ref" ]]; then
  echo "Usage: $0 <git-tag-or-commit>" >&2
  exit 1
fi

require_file "$ROOT_DIR/$ENV_FILE"
require_clean_worktree

git -C "$ROOT_DIR" fetch --all --tags
git -C "$ROOT_DIR" checkout "$target_ref"

compose build backend celery celery-beat frontend
compose run --rm backend alembic upgrade head
compose up -d backend celery celery-beat frontend nginx

echo "Rollback deploy complete: $target_ref"

