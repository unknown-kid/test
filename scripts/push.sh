#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEFAULT_REMOTE="${DEFAULT_REMOTE:-origin}"
DEFAULT_COMMIT_MESSAGE="${DEFAULT_COMMIT_MESSAGE:-chore(repo): update project}"

cd "$ROOT_DIR"

if [[ ! -d .git ]]; then
  echo "Git repository is not initialized." >&2
  exit 1
fi

if ! git remote get-url "$DEFAULT_REMOTE" >/dev/null 2>&1; then
  echo "Git remote '$DEFAULT_REMOTE' is not configured." >&2
  echo "Run ./scripts/setup-git-remote.sh first." >&2
  exit 1
fi

current_branch="$(git rev-parse --abbrev-ref HEAD)"
if [[ -z "$current_branch" || "$current_branch" == "HEAD" ]]; then
  echo "Current branch is detached. Checkout a branch before pushing." >&2
  exit 1
fi

commit_message="${1:-$DEFAULT_COMMIT_MESSAGE}"

git add -A

if git diff --cached --quiet; then
  echo "No staged changes to commit. Pushing current branch only."
else
  git commit -m "$commit_message"
fi

if git rev-parse --verify "${DEFAULT_REMOTE}/${current_branch}" >/dev/null 2>&1; then
  git push "$DEFAULT_REMOTE" "$current_branch"
else
  git push -u "$DEFAULT_REMOTE" "$current_branch"
fi

echo "Push complete: ${DEFAULT_REMOTE}/${current_branch}"
