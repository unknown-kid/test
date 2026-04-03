# Deployment And Upgrade

## Goals

- Keep runtime data separate from the Git working tree.
- Allow one-command Docker deployment.
- Allow safe Git-based upgrades without overwriting runtime data.
- Support rollback to a previous Git tag or commit.


## Layout

- Code repository: this project directory.
- Runtime data: Docker named volumes.
- Backups: `deploy/backups/`.

The production compose file uses Docker named volumes for:

- PostgreSQL
- Redis
- MinIO
- Etcd
- Milvus
- Frontend build artifacts

This means `git pull`, image rebuilds, and container replacement do not delete stored papers or database data.

## Files

- `docker-compose.dev.yml`: development stack with source bind mounts.
- `docker-compose.prod.yml`: deployment stack with image-based services.
- `scripts/deploy.sh`: first deployment.
- `scripts/update.sh`: pull latest Git code and redeploy.
- `scripts/backup.sh`: PostgreSQL backup.
- `scripts/rollback.sh`: redeploy a previous Git ref.
- `scripts/setup-git-remote.sh`: configure the Git remote and branch.
- `scripts/push.sh`: commit and push local changes.

## First-Time Setup

1. Copy `.env.example` to `.env`.
2. Fill in production secrets.
3. Run:

```bash
chmod +x scripts/*.sh
./scripts/deploy.sh
```

## Upgrade

Run:

```bash
./scripts/update.sh
```

What it does:

1. Checks the Git worktree is clean.
2. Pulls the latest code from the current branch.
3. Creates a PostgreSQL backup.
4. Rebuilds images.
5. Runs Alembic migrations.
6. Restarts the app services.

## Rollback

Run:

```bash
./scripts/rollback.sh v1.0.0
```

This redeploys the chosen Git ref against the existing Docker volumes.

## GitHub Push

1. Replace placeholder values in `scripts/setup-git-remote.sh` or pass them as environment variables.
2. Run:

```bash
./scripts/setup-git-remote.sh
```

3. Commit and push:

```bash
./scripts/push.sh "chore(repo): initial commit"
```

## Notes

- Do not rely on live source bind mounts for formal deployments.
- Database migrations should remain backward-compatible where possible.
- Tag stable releases before running upgrades.
