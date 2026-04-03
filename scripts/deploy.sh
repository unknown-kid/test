#!/usr/bin/env bash
set -euo pipefail
source "$(dirname "$0")/common.sh"

require_file "$ROOT_DIR/$ENV_FILE"

compose up -d postgresql redis minio etcd milvus-standalone
compose run --rm backend alembic upgrade head
compose up -d --build backend celery celery-beat frontend nginx

echo "Deployment complete."
echo "App URL: http://localhost:8888"

