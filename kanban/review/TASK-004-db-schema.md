# TASK-004: Postgres schema and migrations

**Status:** REVIEW · **Epic:** EPIC-01 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20 · **Implemented:** 2026-06-20

## Description
Define tables for the entities in 18.1 (Interaction, Position, MandateStrategy, CIORecommendation, ClientDNA, EnrichedHolding cache, Alert, SwapProposal, Moment, MessageDraft, NewsItem, Task) plus an embeddings table. Alembic migrations; enable pgvector.

## Acceptance Criteria
- [x] migrations create all core tables — 15 domain tables + `alembic_version` verified via `\dt`
- [x] pgvector column on notes/DNA — polymorphic `embeddings.vector vector(768)` + HNSW cosine index serves Interaction notes ∪ ClientDNA
- [x] FK/source links support traceability (G2) — hard FKs (Alert.draft_ref, SwapProposal.holding_id, Task.alert_id, …) + polymorphic `citations` table

## Dependencies
TASK-001, TASK-002

## Refs
Requirements §18.1 (data entities), §20 ST3

---

## Technical Analysis (Auto-generated 2026-06-20)

### Dependency status
- **TASK-001** (Docker Compose base stack) — in `in-progress/`, but artifacts fully in place:
  `pgvector/pgvector:pg16` postgres service + `infra/postgres/initdb/01-extensions.sql`
  already runs `CREATE EXTENSION IF NOT EXISTS vector;` on first boot.
- **TASK-002** (FastAPI skeleton) — in `in-progress/`, materially complete. Gives us the async
  SQLAlchemy 2.0 engine + `async_sessionmaker` + `get_session` in `backend/app/db.py`, settings
  in `app/config.py` (async `database_url` via asyncpg), pinned `requirements.txt`.
- Both dependencies are **materially satisfied** — proceeding (same call TASK-002 made re TASK-001).

### Existing Resources Found
- `backend/app/db.py` — async `engine` (`postgresql+asyncpg://…`, `pool_pre_ping`),
  `SessionFactory`, `get_session` dep, `ping_db()`. **No `Base`, no models, no migrations yet**
  — db.py's own docstring explicitly defers schema + Alembic to *this* task.
- `backend/app/config.py` — `Settings.database_url` (asyncpg DSN). NB host/container-port
  decoupling: app talks to `postgres:5432` inside the network; host-published port is remapped.
- `backend/requirements.txt` — already notes "alembic … added by their owning tasks
  (TASK-004 schema)". So adding `alembic` + `pgvector` here is expected, not scope creep.
- `infra/postgres/initdb/01-extensions.sql` — `vector` extension activated at DB init. Our
  first migration should still `CREATE EXTENSION IF NOT EXISTS vector` (idempotent) so the
  schema is reproducible on a DB that wasn't bootstrapped via initdb (e.g. CI).
- **No** existing `models/`, `migrations/`, `alembic.ini`, or `Base` — greenfield ORM layer.

### Entities to model (§18.1 + §19.2 + traceability)
Source (loaded from workbooks by TASK-008/009):
- `Client` *(implied — `clientId` is referenced by every derived entity; the 4 personas:
  Räber, Schneider, Huber, Ammann)*. Carries mandate (Defensive/Balanced/Growth).
- `Interaction` {date, medium, rmName, contact, note} — **note gets an embedding** (G2 search).
- `Position` {assetClass, subAssetClass, region, industryGroup, issuer, security, isin,
  targetCHF, currentCHF, valor, mic, yahoo} — FK→Client.
- `MandateStrategy` {mandate, subAssetClass → targetWeight}.
- `CIORecommendation` {rating, ratingSince, industryGroup, isin, cioView, asOf, BUY/HOLD/SELL,
  not-held-swap-candidate flag}.

Derived (built by our system — each carries `sources`/evidence for G2):
- `ClientDNA` {clientId, name, mandate, values[], exclusions[], tilts[], styleProfile,
  businessContext, family, lifeEvents[], promises[], temperament, sources[noteRef]} —
  **gets an embedding**; structured lists as JSONB.
- `EnrichedHolding` (cache) = Position + {tags, livePrice, fitScore, conflicts[]}.
- `Alert` {client, class, actionType ∈ {Trade,ReachOut,Acknowledge,Watch}, severity
  ∈ {Critical,Attention,FYI}, due, trigger, evidence[], why, suggestedAction, draftRef,
  confidence, status} (§15 AL3).
- `SwapProposal` {holding, candidate, dnaReason, cioView, mandateNeutral, fitGain, sources}.
- `Moment` {client, event, why, channel, draftRef, sources} (UC-6).
- `MessageDraft` {clientId, factSheet, draftText, style, factsUsed[], provenance[], channel}.
- `NewsItem` {headline, source, url, time, sentiment, matchedHoldings[], matchedThemes[],
  impact} (§13).
- `Task` {clientId, source, executionMode ∈ {Auto,Manual}, status, result, sources}
  (§19.2 TK2/TK6).
- `Embedding` table — pgvector column, polymorphic (`owner_type`, `owner_id`) so Interaction
  notes **and** ClientDNA share one index; satisfies AC "pgvector column on notes/DNA".

### Dependencies Required
- **Backend packages (add to `requirements.txt`):**
  - `alembic==1.14.*` (migrations).
  - `pgvector==0.3.*` (SQLAlchemy `Vector` column type for models + migrations).
- **No** new frontend packages, no new Docker services.
- **Migrations:** introduce Alembic. Use the **async template** (`alembic init -t async`) so
  migrations run on the existing asyncpg DSN — avoids pulling in a second driver
  (psycopg2). `env.py` reads `settings.database_url`; `target_metadata = Base.metadata`.
- **Embedding dimension** must match the model TASK-015 will use (Ollama embeddings). Park as a
  config constant (e.g. `EMBED_DIM`, default 768 for `nomic-embed-text`); confirm with TASK-015.

### Impact Assessment
#### Files to Create
- `backend/app/models/__init__.py` — declarative `Base` + re-exports (single `Base.metadata`).
- `backend/app/models/*.py` — one module per entity group (source / derived / embedding).
- `backend/alembic.ini`, `backend/migrations/env.py` (async), `migrations/script.py.mako`,
  `migrations/versions/0001_initial_schema.py`.
- (maybe) `backend/app/models/enums.py` — Mandate, ActionType, Severity, AlertStatus,
  ExecutionMode, TaskStatus as Python/DB enums.

#### Files to Modify
- `backend/requirements.txt` — add `alembic`, `pgvector`.
- `backend/app/db.py` — import models' `Base` so metadata is registered; optionally expose it.
  No change to engine/session wiring.
- `backend/Dockerfile` / compose `backend` — ensure migrations run (entrypoint
  `alembic upgrade head` before uvicorn, **or** a documented one-shot `docker compose exec
  backend alembic upgrade head`). Recommend the latter for the demo to keep startup simple.

#### Components Affected
- TASK-008/009 (workbook loaders): **HIGH (enabling)** — they insert into these tables; column
  names/types must match the workbook conventions (CHF amounts, Excel-serial dates → `Date`,
  Valor/MIC/ISIN as text). Align column names with §10 now.
- TASK-015 (embeddings): **MEDIUM** — depends on the `Embedding` table + `EMBED_DIM`.
- TASK-016/017 (DNA extract/style), 020/021 (fit/swap), 032 (alerts), 049 (task model): **MEDIUM**
  — consume these tables; this is their schema contract.
- Existing routers/health: **LOW** — no contract change.

#### API Changes
- None (this task is schema only; no endpoints).

#### Database Changes
- Net-new schema: ~13 tables + 1 embeddings table, with FKs Client→(Interaction, Position,
  ClientDNA, Alert, Moment, MessageDraft, Task) and source-link FKs/JSONB for G2 traceability.
- `vector` extension (idempotent `CREATE EXTENSION` in migration 0001).
- Indexes: FK columns; pgvector ANN index (`ivfflat`/`hnsw`) on `Embedding.vector`; lookup
  indexes on `Position.valor`, `Position.isin`, `CIORecommendation.industry_group`,
  `Alert.(client_id,status,severity)`.

### Traceability design (G2 — the AC that matters most)
Every derived row must point back to its evidence. Two complementary mechanisms:
1. **Hard FKs** where the link is 1:1/1:N and known (e.g. `Alert.draft_ref → MessageDraft.id`,
   `SwapProposal.holding_id → Position.id`, `Task.alert_id → Alert.id`).
2. **Polymorphic evidence rows** for the many-to-many "this claim is backed by these
   notes/news/CIO rows": a small `Citation`/`evidence` table or a typed JSONB `sources[]`
   ({source_type, source_id}) on each derived entity. Recommend a normalised
   `Citation(owner_type, owner_id, source_type, source_id, note)` table so traceability is
   queryable and uniform across Alert/DNA/SwapProposal/MessageDraft/Moment.

### Implementation Checklist
- [ ] Add `alembic` + `pgvector` to `requirements.txt`; rebuild backend image.
- [ ] Create `app/models/Base` (single declarative base) — reuse, don't redefine per module.
- [ ] One module per entity group; enums centralised; `Mapped[]`/`mapped_column` (SA 2.0 style).
- [ ] `Embedding` table polymorphic over (owner_type, owner_id) — one index serves notes + DNA.
- [ ] `Citation` table for uniform G2 source links; hard FKs where 1:N is known.
- [ ] `alembic init -t async`; `env.py` uses `settings.database_url`; `CREATE EXTENSION vector`
      first in migration 0001.
- [ ] Column names/types match §10 workbook conventions (Valor/MIC/ISIN text; CHF numeric;
      dates as `Date` after Excel-serial conversion — conversion itself is TASK-007/008).
- [ ] pgvector ANN index + FK/lookup indexes.
- [ ] `EMBED_DIM` parameterised (default 768) — coordinate with TASK-015.
- [ ] Backwards compatible with TASK-002 db.py (no engine/session changes).
- [ ] Self-documenting models; docstring each table to its §18.1 entity.

### Risk Analysis
- **Risk Level:** MEDIUM
- **Main Risks:**
  - *Async Alembic friction* (async `env.py` is fiddlier than sync) → use the official
    `-t async` template verbatim; smoke-test `upgrade head` / `downgrade base` in the container.
  - *Embedding dimension churn* (model not chosen until TASK-015) → make `EMBED_DIM` a config
    constant; a later change is a one-line `ALTER`/new migration, not a redesign.
  - *Schema drift vs. workbook reality* (loaders TASK-008/009 find columns we mismodelled) →
    ground every source-table column in §10 now; keep derived-entity free-text as JSONB to
    absorb surprises without migrations.
  - *Over-normalising for a hackathon* → JSONB for soft/iterating fields (DNA lists, evidence,
    factsUsed); reserve hard columns + FKs for the join/filter/traceability paths.
  - *Migrations not applied on fresh boot* → document `alembic upgrade head` (one-shot exec or
    entrypoint); don't rely solely on initdb.

### Estimated Effort
- Original: **M**
- Adjusted: **M** — ~13 tables + embeddings + citations, async Alembic bootstrap, and aligning
  source columns to §10. Wide but mechanical; the only real unknowns are async-Alembic wiring
  and `EMBED_DIM`, both de-risked above.

### Verification (close-out)
```bash
docker compose exec backend alembic upgrade head
docker compose exec backend alembic downgrade base && \
  docker compose exec backend alembic upgrade head   # round-trips cleanly
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -c "\dt"   # all tables present
docker compose exec postgres psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
  -c "\d embeddings"                                  # vector column present
```

---

## Implementation (2026-06-20)

Built the full ORM layer + first migration, run automatically on container start.

**Files created**
- `backend/app/models/` — declarative `Base` (`__init__.py`, re-exports all models so
  `Base.metadata` is complete for autogenerate); `mixins.py` (UUID PK via `gen_random_uuid()` +
  `created_at`/`updated_at`); `enums.py` (9 native PG enums: Mandate, CIORating, ActionType AL2,
  Severity AL4, AlertStatus AL7, DraftStatus, ExecutionMode TK2, TaskStatus TK6, SourceType);
  `source.py` (Client*, Interaction, Position, MandateStrategy, CIORecommendation — columns
  match §10); `derived.py` (ClientDNA, EnrichedHolding, NewsItem, MessageDraft, SwapProposal,
  Moment, Alert, Task — soft/iterating fields as JSONB); `citation.py` (polymorphic G2 evidence);
  `embedding.py` (polymorphic `Vector(settings.embed_dim)`).
- `backend/alembic.ini`, `backend/migrations/env.py` (async template, DSN from `app.config` —
  single asyncpg driver, no psycopg2), `migrations/script.py.mako`,
  `migrations/versions/0001_initial_schema.py` (idempotent `CREATE EXTENSION vector` → enums →
  15 tables in FK order → FK/lookup/GIN/HNSW indexes).
- `backend/entrypoint.sh` — `alembic upgrade head` then uvicorn.

**Files modified**
- `requirements.txt` — `alembic==1.14.0`, `pgvector==0.3.6`.
- `app/config.py` — `embed_dim` (default 768; coordinate with TASK-015).
- `app/db.py` — imports `Base` from `app.models` (registers metadata; no engine/session change).
- `Dockerfile` — `ENTRYPOINT ["sh", "/app/entrypoint.sh"]` (replaces uvicorn CMD).

**Verified live** (`docker compose`): backend rebuilt (alembic+pgvector installed) →
`alembic upgrade  -> 0001` on boot → uvicorn up → `/health` & `/health/ready` (postgres ok) 200.
`downgrade base` → `upgrade head` round-trips cleanly. `\dt` shows all 15 domain tables +
`alembic_version`; `\d embeddings` shows `vector(768)` + `ix_embeddings_vector_hnsw` (cosine);
`vector` extension present; 9 enum types created.

**Decisions / notes**
- UUID PKs (`gen_random_uuid()`, built into pg16); full §18.1 field set now (schema contract for
  downstream tasks); migrations auto-run via entrypoint (compose waits for healthy postgres).
- Native enum DB labels are the Python enum member *names* (SQLAlchemy default) — consistent
  between ORM and migration; loaders convert workbook strings → enum members.
- Soft fields kept JSONB to absorb loader surprises without migrations.
- **Out of scope** (owned elsewhere): instrument tag table (TASK-010; tags live in
  `enriched_holdings.tags` JSONB for now), DNA/fit/swap/alert/task *logic* (016/017/020/021/032/049).

Ready for `/task-review`.
