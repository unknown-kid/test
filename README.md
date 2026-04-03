# Paper Reading Platform

## Modes

- Development: `docker compose -f docker-compose.dev.yml up --build`
- Production-style deployment: `./scripts/deploy.sh`

## Upgrade Flow

- Track code in Git.
- Store runtime data in Docker volumes.
- Use `./scripts/update.sh` for pull + backup + migrate + redeploy.
- Use `./scripts/rollback.sh <tag-or-commit>` for rollback.
- Use `./scripts/setup-git-remote.sh` to configure the GitHub remote.
- Use `./scripts/push.sh "type(scope): summary"` for one-command commit and push.

See `docs/deployment.md` for details.
