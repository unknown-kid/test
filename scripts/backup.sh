#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

require_file "$ROOT_DIR/$ENV_FILE"

timestamp="$(date +%Y%m%d_%H%M%S)"
backup_path="$BACKUP_DIR/postgres_${PROJECT_NAME}_${timestamp}.sql"

compose exec -T postgresql pg_dump -U "${POSTGRES_USER:-paperapp}" -d "${POSTGRES_DB:-paperdb}" > "$backup_path"

echo "Backup written to $backup_path"

