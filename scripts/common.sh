#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
COMPOSE_FILE="${COMPOSE_FILE:-docker-compose.prod.yml}"
ENV_FILE="${ENV_FILE:-.env}"
BACKUP_DIR="${BACKUP_DIR:-$ROOT_DIR/deploy/backups}"

if [[ -f "$ROOT_DIR/$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ROOT_DIR/$ENV_FILE"
  set +a
fi

PROJECT_NAME="${DOCKER_COMPOSE_PROJECT:-paperapp}"

mkdir -p "$BACKUP_DIR"

compose_bin() {
  if docker compose version >/dev/null 2>&1; then
    echo "docker compose"
    return
  fi
  if docker-compose version >/dev/null 2>&1; then
    echo "docker-compose"
    return
  fi
  echo "Docker Compose is not available." >&2
  exit 1
}

compose() {
  local cmd
  cmd="$(compose_bin)"
  if [[ "$cmd" == "docker compose" ]]; then
    docker compose -f "$ROOT_DIR/$COMPOSE_FILE" -p "$PROJECT_NAME" "$@"
    return
  fi
  docker-compose -f "$ROOT_DIR/$COMPOSE_FILE" -p "$PROJECT_NAME" "$@"
}

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "Missing required file: $path" >&2
    exit 1
  fi
}

require_clean_worktree() {
  if ! git -C "$ROOT_DIR" diff --quiet || ! git -C "$ROOT_DIR" diff --cached --quiet; then
    echo "Working tree has uncommitted changes. Commit or stash before update." >&2
    exit 1
  fi
}
