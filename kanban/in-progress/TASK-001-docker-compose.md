# TASK-001: Docker Compose base stack

**Status:** IN-PROGRESS · **Epic:** EPIC-01 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Author docker-compose with postgres+pgvector, redis, minio, pgadmin, mailhog services, healthchecks, named volumes, and a shared network. No Azure.

## Acceptance Criteria
- [ ] docker compose up brings all services healthy
- [ ] pgvector extension available in the postgres image
- [ ] minio console + pgadmin reachable locally
- [ ] .env drives ports/credentials

## Dependencies
None (foundational).

## Refs
Requirements §20 (Docker Compose services)

---

## Technical Analysis (Auto-generated 2026-06-20)

### Scope clarification
§20 lists **9** compose services (`frontend · backend · ollama · postgres · redis · minio ·
pgadmin · mailhog · mcp-proxy`). TASK-001 owns only the **base data/dev services**:
`postgres (+pgvector) · redis · minio · pgadmin · mailhog`. The application/runtime services
are split out:
- `backend` (FastAPI) → TASK-002
- `frontend` (React/Vite) → TASK-003
- `ollama` (Gemma 3 12B) → TASK-012 (LLM abstraction)
- `mcp-proxy` (SIX MCP connector) → TASK-013 (SIX client)

To keep `docker compose up` working incrementally, author this compose file so app services can
be **added later without restructuring** (shared network + named volumes defined now; app
services appended by their tasks). TASK-005 (Redis+MinIO client wiring) and TASK-006 (config &
secrets) depend on the service definitions and `.env` keys established here.

### Existing Resources Found
- **No** existing `docker-compose.yml`, `Dockerfile`, root `.env`, or `backend/` tree —
  genuinely foundational (greenfield).
- `demo/.env.example` — reference only for **provider** credential names (Phoeniqs / SIX MCP /
  NewsAPI). These belong to later tasks; not needed for the base stack, but mirror the naming
  convention (`<SERVICE>_<FIELD>`).
- No CI / lint / test harness configured at repo root (per CLAUDE.md) — nothing to integrate with.

### Dependencies Required
- **Docker services (this task):** `postgres`, `redis`, `minio`, `pgadmin`, `mailhog`.
- **Images:**
  - Postgres+pgvector → `pgvector/pgvector:pg16` (extension preinstalled; avoids building a
    custom image — satisfies AC "pgvector extension available in the postgres image").
  - Redis → `redis:7-alpine`.
  - MinIO → `minio/minio:latest` (console on `:9001`, API on `:9000`).
  - pgAdmin → `dpage/pgadmin4:latest`.
  - MailHog → `mailhog/mailhog:latest` (SMTP `:1025`, UI `:8025`).
- **Frontend packages:** none.
- **Backend packages:** none (this task is infra only).
- **Migrations:** none yet — Alembic + schema is TASK-004. Add an `initdb` mount only for
  `CREATE EXTENSION IF NOT EXISTS vector;` so the extension is enabled on first boot.

### Impact Assessment
#### Files to Create
- `docker-compose.yml` — the 5 base services + network + volumes.
- `.env.example` (root) — ports & credentials for all services; the source of AC "env drives
  ports/credentials".
- `.env` (root, git-ignored) — local copy; ensure `.gitignore` excludes it.
- `infra/postgres/initdb/01-extensions.sql` (or similar) — `CREATE EXTENSION vector;`.
- `.gitignore` (create/extend) — ignore `.env`, named-volume bind dirs if any.

#### Components Affected
- TASK-002/003/012/013: **LOW** — they append services to this compose file (additive).
- TASK-005 (Redis/MinIO wiring): **MEDIUM** — consumes hostnames/ports/creds defined here.
- TASK-006 (config & secrets): **MEDIUM** — formalises the `.env` schema started here.

#### API Changes
- None.

#### Database Changes
- New `postgres` service with `vector` extension enabled at init. No schema/tables yet
  (TASK-004 owns the schema + Alembic).

### Implementation Checklist
- [ ] Use `pgvector/pgvector:pg16` so the extension ships in the image (don't build custom).
- [ ] `initdb` SQL enables `vector` extension on first boot.
- [ ] Every service has a **healthcheck**; `depends_on: condition: service_healthy` where it
      matters (so `docker compose up` reports healthy per AC).
- [ ] **Named volumes** for postgres data, minio data, pgadmin data (persistence across `down`).
- [ ] Single **shared bridge network** (e.g. `wealthnet`) so later app services join cleanly.
- [ ] All ports, users, passwords, bucket names driven by **`.env`** (with `.env.example`
      committed, `.env` git-ignored).
- [ ] MinIO console + pgAdmin reachable on documented localhost ports.
- [ ] Pin image tags (no bare `latest` for postgres/redis to keep dev reproducible).
- [ ] README/compose comment noting app services (backend/frontend/ollama/mcp-proxy) are added
      by later tasks.

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - *pgvector image variant drift* → pin `pgvector/pgvector:pg16`; verify `CREATE EXTENSION`
    succeeds in a smoke test before closing.
  - *Port collisions on dev machines* (5432/6379/9000/9001/5050/8025) → all ports parameterised
    via `.env` so they're overridable.
  - *Volume name clashes with other local projects* → prefix volumes with project name.
  - *Scope creep into app services* → explicitly deferred to TASK-002/003/012/013.

### Estimated Effort
- Original: **M**
- Adjusted: **S–M** — scope is 5 stock images with healthchecks/volumes/`.env`; no custom
  builds. Custom-image work (backend/frontend) lives in later tasks.

### Verification (close-out smoke test)
```bash
docker compose up -d
docker compose ps                     # all 5 services -> healthy
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "CREATE EXTENSION IF NOT EXISTS vector; SELECT extname FROM pg_extension WHERE extname='vector';"
# open http://localhost:${MINIO_CONSOLE_PORT} (MinIO) and http://localhost:${PGADMIN_PORT} (pgAdmin)
```
