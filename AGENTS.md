# Repository Guidelines

## Project Structure & Module Organization
This repository is a two-part app with infrastructure at the root:

- `backend/`: FastAPI service (`app/routers`, `app/services`, `app/models`, `app/schemas`, `app/tasks`, `alembic/` migrations).
- `frontend/`: Vite + React + TypeScript UI (`src/pages`, `src/components`, `src/api`, `src/stores`, `public/`).
- Root infra: `docker-compose.yml`, `nginx.conf`, `init-scripts/`, and `.env`.

Keep business logic in `backend/app/services`, HTTP layer in `backend/app/routers`, and frontend state/API calls in `frontend/src/stores` + `frontend/src/api`.

## Build, Test, and Development Commands
- `docker compose up --build`: Start full stack (PostgreSQL, Redis, MinIO, Milvus, backend, worker, frontend, nginx).
- `cd backend && pip install -r requirements.txt`: Install backend dependencies.
- `cd backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000`: Run backend locally.
- `cd frontend && npm ci`: Install frontend dependencies.
- `cd frontend && npm run dev`: Run frontend dev server.
- `cd frontend && npm run build`: Type-check and build production assets.
- `cd frontend && npm run preview`: Preview frontend production build.

## Coding Style & Naming Conventions
- Python: 4-space indentation, `snake_case` for functions/modules, `PascalCase` for classes and Pydantic/ORM models.
- TypeScript/React: 2-space indentation, `PascalCase` for components/pages, `camelCase` for hooks/helpers/stores.
- Keep route files focused (`routers/*.py`), move reusable logic to services.
- No formatter/linter is configured yet; keep style consistent with surrounding code before introducing tooling.

## Testing Guidelines
There is currently no dedicated test suite (`tests/` is absent). For new work:

- Backend: add `pytest` tests under `backend/tests/` (e.g., `test_auth_service.py`).
- Frontend: add component/unit tests under `frontend/src/__tests__/` (e.g., `LoginForm.test.tsx`).
- Minimum expectation for PRs: include at least one automated test or a clear manual verification checklist.

## Commit & Pull Request Guidelines
Git history is not available in this workspace, so follow this baseline:

- Commit format: `type(scope): summary` (for example, `feat(auth): add refresh token rotation`).
- Keep commits atomic and focused by module (`backend`, `frontend`, or infra).
- PRs should include: purpose, key changes, verification steps, env/config changes, and UI screenshots for frontend updates.
- Link related issues/tasks and call out migration or breaking changes explicitly.

## Security & Configuration Tips
- Store secrets only in `.env`; never hardcode credentials in code or commit real secrets.
- Review CORS/JWT settings before production deployment.
- Validate changes to `docker-compose.yml` and `nginx.conf` with a local smoke test.
