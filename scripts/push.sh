#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_BRANCH="${DEFAULT_BRANCH:-<main>}"
DEFAULT_REMOTE="${DEFAULT_REMOTE:-origin}"
DEFAULT_COMMIT_MESSAGE="${DEFAULT_COMMIT_MESSAGE:-chore: update project}"

cd "$ROOT_DIR"

if [[ ! -d .git ]]; then
  echo "Git repository is not initialized." >&2
  exit 1
fi

if git diff --quiet && git diff --cached --quiet; then
  echo "No changes to commit."
  exit 0
fi

commit_message="${1:-$DEFAULT_COMMIT_MESSAGE}"

git add -A

if git diff --cached --quiet; then
  echo "No staged changes to commit."
  exit 0
fi

git commit -m "$commit_message"
git push "$DEFAULT_REMOTE" "$DEFAULT_BRANCH"

echo "Push complete: ${DEFAULT_REMOTE}/${DEFAULT_BRANCH}"

