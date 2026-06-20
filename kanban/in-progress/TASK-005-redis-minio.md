# TASK-005: Redis and MinIO client wiring

**Status:** IN-PROGRESS · **Epic:** EPIC-01 · **Priority:** P0 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Add Redis (cache + queues) and MinIO (S3) clients with helper modules and bucket bootstrap.

## Acceptance Criteria
- [x] redis ping works from backend
- [x] minio bucket created on startup
- [x] helper utils for put/get object and enqueue/dequeue

## Dependencies
TASK-001, TASK-002

## Refs
Requirements §20 ST3

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found
- **Compose (TASK-001):** `redis:7-alpine` and `minio/minio:RELEASE.2025-04-22…` services
  already defined on `wealthnet` with healthchecks and named volumes (`redisdata`,
  `miniodata`). `backend` already `depends_on` both with `condition: service_healthy`, so the
  app boots only once Redis/MinIO are live. **No client code exists yet** — greenfield wiring.
- **Settings (`app/config.py`):** already exposes `redis_host`/`redis_port` (container-port
  alias `REDIS_CONTAINER_PORT`, defaults to 6379) and a computed `redis_url`
  (`redis://{host}:{port}/0`). **MinIO has env keys but no Settings fields yet** — only
  `MINIO_ROOT_USER`/`MINIO_ROOT_PASSWORD`/`MINIO_API_PORT`/`MINIO_CONSOLE_PORT` exist in
  `.env`, consumed by compose, not by the app.
- **DB precedent to mirror (`app/db.py`):** module-level singleton engine + factory +
  `ping_db()` connectivity check. Redis/MinIO clients should follow the **same shape** (one
  module-level client per service, a `ping_*()` for readiness).
- **Readiness probe (`app/routers/health.py`):** `GET /health/ready` currently checks only
  Postgres and reports per-dependency in `checks{}`. This is the integration point for the
  "redis ping works" AC — add `redis` and `minio` checks alongside `postgres`.
- **Lifespan hook (`app/main.py`):** `lifespan()` is where the "minio bucket created on
  startup" AC is satisfied (bootstrap the bucket on app start, idempotently).
- **Logging (`app/logging.py`):** `get_logger(__name__)` structlog pattern — reuse for client
  init / bucket-bootstrap log lines.

### Dependencies Required
- **Backend packages (add to `requirements.txt`, pinned):**
  - `redis==5.2.1` — official client ships `redis.asyncio` (async ping + list ops for
    enqueue/dequeue via `LPUSH`/`BRPOP`). No separate aioredis needed.
  - `minio==7.2.x` (S3 client; lightweight, matches the MinIO server) **or** `boto3`. Lean
    `minio` SDK preferred — smaller, purpose-built, simpler bucket bootstrap
    (`make_bucket`/`bucket_exists`). Decide at implementation; default = `minio`.
- **Frontend packages:** none.
- **Database migrations:** none.
- **Docker services:** `redis`, `minio` — already running (TASK-001). No compose changes
  expected beyond confirming `depends_on` (already present).

### Impact Assessment
#### Files to Create
- `app/redis_client.py` — module-level async Redis client from `settings.redis_url`;
  `ping_redis()`; queue helpers `enqueue(queue, payload)` / `dequeue(queue, timeout)`
  (JSON-encode payloads); optional `cache_get`/`cache_set` with TTL.
- `app/storage.py` (MinIO/S3) — module-level `Minio` client; `ensure_bucket()` (idempotent,
  called from lifespan); `put_object(key, data, content_type)` / `get_object(key) -> bytes`;
  `ping_storage()` (e.g. `bucket_exists`).

#### Files to Modify
- `app/config.py` — add MinIO fields (`minio_endpoint` host:port, `minio_root_user`,
  `minio_root_password`, `minio_bucket`, `minio_secure=False` for local http). Mirror the
  Postgres/Redis container-vs-host-port note: the app talks to `minio:9000` **inside** the
  network, not the host-published `MINIO_API_PORT`.
- `app/main.py` — call `ensure_bucket()` (and optionally a Redis connectivity log) in
  `lifespan()` startup; close clients on shutdown.
- `app/routers/health.py` — extend `/health/ready` with `redis` and `minio` checks
  (same report-don't-raise pattern as the Postgres check).
- `requirements.txt` — add the two pinned deps.
- `.env.example` / `.env` — add `MINIO_BUCKET` (e.g. `wealth`) under the MinIO section; the
  app needs the bucket name (host/creds keys already exist).

#### Components Affected
- TASK-002 health router: **LOW** (additive checks).
- TASK-002 lifespan: **LOW** (additive bootstrap).
- TASK-006 (config & secrets): **LOW** — will formalise the MinIO keys added here.
- Downstream consumers — queues for the **news poller/fan-out** (TASK-029/030) and object
  storage for **voice notes** (TASK-046) and **fact sheets** (TASK-037): **LOW** now (they
  consume these helpers later; design the helper signatures to be generic).

#### API Changes
- `GET /health/ready` response `checks{}` gains `redis` and `minio` keys. Additive,
  backwards-compatible.

#### Database Changes
- None.

### Implementation Checklist
- [ ] Reuse the `app/db.py` singleton+`ping_*` shape for both clients (don't reinvent).
- [ ] Add MinIO fields to existing `Settings` (extend in place — don't fork config).
- [ ] Bucket bootstrap is **idempotent** (`bucket_exists` guard) and runs in lifespan startup.
- [ ] Redis queue helpers JSON-encode/decode payloads; `dequeue` supports blocking timeout.
- [ ] Extend `/health/ready` — report per-dependency, never raise (match Postgres check).
- [ ] App talks to in-network ports (`redis:6379`, `minio:9000`), not host-published ports.
- [ ] Pin new deps in `requirements.txt`; rebuild backend image (requirements changed).
- [ ] Structlog log lines on client init / bucket creation.
- [ ] Graceful client close on lifespan shutdown.

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - *requirements.txt change needs image rebuild* → `docker compose build backend` (bind-mount
    reload only picks up code, not deps).
  - *MinIO endpoint confusion (host vs container port)* → app uses `minio:9000` + `secure=False`;
    document in `.env` like the existing Postgres/Redis note.
  - *Redis client not closed on reload* → close in lifespan shutdown; `redis.asyncio` pools are
    forgiving but be explicit.
  - *minio SDK is sync* → call from async paths via a threadpool if it ever blocks the loop;
    bucket bootstrap at startup is fine synchronously.

### Estimated Effort
- Original: **S**
- Adjusted: **S** — two small client modules + config/health/lifespan touch-ups; all infra and
  patterns already exist.

### Verification (close-out smoke test)
```bash
docker compose build backend && docker compose up -d backend
curl -s localhost:8000/health/ready | jq          # checks.redis == ok, checks.minio == ok
docker compose exec redis redis-cli ping          # PONG
# bucket exists after startup:
docker compose exec minio sh -c "mc alias set local http://localhost:9000 \$MINIO_ROOT_USER \$MINIO_ROOT_PASSWORD && mc ls local/"
```

---

## Implementation (2026-06-20)

Wired both clients onto the TASK-002 skeleton, mirroring the `app/db.py`
singleton + `ping_*()` pattern:
- `app/redis_client.py` — `redis.asyncio` module-level client from `redis_url`;
  `ping_redis()`, `close_redis()`, queue helpers `enqueue`/`dequeue`
  (`LPUSH`/`BRPOP`, JSON), cache helpers `cache_set`/`cache_get` (TTL).
- `app/storage.py` — `minio` SDK singleton on the in-network `minio:9000`
  endpoint (`secure=False`); idempotent `ensure_bucket()`, `put_object`,
  `get_object`, `ping_storage()`.
- `app/config.py` — added MinIO `Settings` fields + computed `minio_endpoint`
  (`host:port`), reusing the Postgres/Redis container-port alias convention.
- `app/main.py` — `ensure_bucket()` + `ping_redis()` in lifespan startup
  (non-fatal, logged), `close_redis()` on shutdown.
- `app/routers/health.py` — `/health/ready` now reports `redis` + `minio`
  alongside `postgres` (report-don't-raise).
- `requirements.txt` — `redis==5.2.1`, `minio==7.2.15` (image rebuilt).
- `.env`/`.env.example` — added `MINIO_BUCKET=wealth`.

**Verified live** (`docker compose build backend && up -d`):
- backend → healthy; `GET /health/ready` →
  `{"status":"ok","checks":{"postgres":"ok","redis":"ok","minio":"ok"}}`.
- `redis-cli ping` → `PONG`; `mc ls local/` shows the `wealth/` bucket created
  on startup.
- In-container round-trip: object put/get, queue enqueue/dequeue, and cache
  set/get all pass.

Ready for `/task-review`.

### Dependency note
TASK-001 and TASK-002 sit in `in-progress/` (not `done/`), but both are materially complete:
the compose `redis`/`minio` services run with healthchecks and the FastAPI skeleton (config,
db, health, lifespan) is live and verified. The wiring points this task needs all exist.
Proceeding without blocking, consistent with TASK-002's handling of the same situation.
