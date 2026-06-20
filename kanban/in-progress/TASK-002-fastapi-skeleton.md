# TASK-002: FastAPI backend skeleton

**Status:** IN-PROGRESS · **Epic:** EPIC-01 · **Priority:** P0 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Started:** 2026-06-20

## Description
Scaffold the FastAPI app: settings via pydantic, /health, routers package, db session, structured logging, CORS.

## Acceptance Criteria
- [x] GET /health returns ok
- [x] settings loaded from env
- [x] app runs in its compose container with reload

## Dependencies
TASK-001

## Refs
Requirements §20 (Backend: FastAPI)

---

## Implementation (2026-06-20)

Scaffolded `backend/` (FastAPI, Python 3.12):
- `app/config.py` — pydantic-settings `Settings`; reads the shared root `.env`
  (`extra="ignore"`). Builds async `database_url`/`redis_url`. **Container ports
  are decoupled from the host-published ports** (`POSTGRES_PORT`/`REDIS_PORT` in
  `.env` are remapped to 15432/16379 to avoid local collisions; the in-network
  app must still hit 5432/6379, so those bind to dedicated
  `POSTGRES_CONTAINER_PORT`/`REDIS_CONTAINER_PORT` aliases that default correctly).
- `app/logging.py` — structlog; console renderer in dev, JSON otherwise.
- `app/db.py` — async SQLAlchemy engine + `async_sessionmaker` + `get_session`
  dependency + `ping_db()`. No models/migrations (those are TASK-004).
- `app/routers/health.py` — `GET /health` (liveness) and `GET /health/ready`
  (readiness; pings Postgres → 503 if down).
- `app/main.py` — app factory: settings, logging, CORS, lifespan log, health router.
- `Dockerfile` (python:3.12-slim), `requirements.txt` (pinned), `.dockerignore`.
- `docker-compose.yml` — activated the `backend` service (build, `env_file: .env`,
  bind-mount for `--reload`, depends_on healthy postgres/redis/minio, healthcheck).
- `.env`/`.env.example` — added Backend section (`BACKEND_PORT`, `ENVIRONMENT`,
  `LOG_LEVEL`, `CORS_ORIGINS`, `POSTGRES_HOST`, `REDIS_HOST`).

**Verified live:** `docker compose up -d backend` → container healthy; `/health`,
`/health/ready` (postgres ok), and `/` all return 200; reload watcher active.

**Dependency note:** TASK-001 was in `in-progress/` (not `done/`) at start, but its
artifacts (compose base stack, `.env`, pgvector initdb) were fully in place and the
compose file already reserved a `backend` stub for this task — so the dependency was
materially satisfied. Proceeded without blocking.

Ready for `/task-review`.
