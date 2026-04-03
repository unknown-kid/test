#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REMOTE_NAME="${REMOTE_NAME:-origin}"
REMOTE_URL="${REMOTE_URL:-https://github.com/unknown-kid/test.git}"
DEFAULT_BRANCH="${DEFAULT_BRANCH:-main}"
GIT_USER_NAME="${GIT_USER_NAME:-unknown-kid}"
GIT_USER_EMAIL="${GIT_USER_EMAIL:-379550761@qq.com}"

cd "$ROOT_DIR"

if [[ ! -d .git ]]; then
  echo "Git repository is not initialized." >&2
  exit 1
fi

git config user.name "$GIT_USER_NAME"
git config user.email "$GIT_USER_EMAIL"

if git remote get-url "$REMOTE_NAME" >/dev/null 2>&1; then
  git remote set-url "$REMOTE_NAME" "$REMOTE_URL"
else
  git remote add "$REMOTE_NAME" "$REMOTE_URL"
fi

git branch -M "$DEFAULT_BRANCH"

echo "Remote configured:"
echo "  name:   $REMOTE_NAME"
echo "  url:    $REMOTE_URL"
echo "  branch: $DEFAULT_BRANCH"

