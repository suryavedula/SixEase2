# TASK-008: Load portfolios, CIO list, mandates

**Status:** IN-PROGRESS · **Epic:** EPIC-02 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Ingest Portfolio Strategies, CIO Recommendation List, and the three Sample Portfolios into DB with identifiers (Valor/MIC/ISIN/Yahoo) and Industry Group.

## Acceptance Criteria
- [x] positions, CIO rows, mandate weights loaded
- [x] Current vs Target retained for drift
- [x] idempotent reload

## Dependencies
TASK-004, TASK-007

## Refs
Requirements §10.2, §10.4

---

## Technical Analysis (Auto-generated 2026-06-20)

### Dependency Status
- **TASK-004** (DB schema) — in `review/`, fully implemented and verified live. The tables
  `clients`, `positions`, `mandate_strategies`, `cio_recommendations` are created with the
  correct columns, indexes, and FK structure. Migrations auto-run via `entrypoint.sh`.
- **TASK-007** (XLSX parser) — in `in-progress/`, `backend/app/xlsx.py` fully implemented:
  `load_sheet(path, sheet) → list[dict]`, `load_workbook(path) → dict[str, list[dict]]`,
  and `excel_serial_to_date(serial) → date`. Zero new deps — pure stdlib.
- Both dependencies are **materially satisfied** — proceeding.

### Existing Resources Found
- **`backend/app/xlsx.py`** — `load_sheet` / `load_workbook` / `excel_serial_to_date`.
  These are the primary reuse points; the loader calls them directly. No re-parsing needed.
- **`backend/app/models/source.py`** — ORM models `Client`, `Position`, `MandateStrategy`,
  `CIORecommendation` with all columns verified against the workbook (see mapping below).
- **`backend/app/models/enums.py`** — `Mandate` (DEFENSIVE/BALANCED/GROWTH), `CIORating`
  (BUY/HOLD/SELL). Loaders convert workbook strings → these enum members.
- **`backend/app/db.py`** — `SessionFactory` (async_sessionmaker), `get_session` FastAPI dep.
  The loader uses `SessionFactory` directly (not via HTTP).
- **`backend/app/config.py`** — `Settings` with `extra="ignore"`. Adding `data_dir` here
  is the right place (needs a `DATA_DIR` env var + compose volume mount).
- **`backend/app/routers/health.py`** — pattern to follow for the admin seed endpoint.
- **`backend/app/main.py`** — router registration point; comment says "domain routers
  appended by later tasks." Include admin router here.

### Workbook Column Mapping (verified by live parse)

#### `Portfolio Strategies` → `mandate_strategies`
Each workbook row expands to **3** DB rows (one per mandate):

| Workbook column | Mandate | ORM field |
|---|---|---|
| `Sub-Asset Class` | all | `sub_asset_class` |
| `Def %` | DEFENSIVE | `target_weight` |
| `Balanced %` | BALANCED | `target_weight` |
| `Growth %` | GROWTH | `target_weight` |

`Asset Class` and `Benchmark / Index Reference` are not stored (not in schema).
Upsert key: unique index `ix_mandate_strategies_mandate_sac` on `(mandate, sub_asset_class)`.

#### `CIO Recommendation List` → `cio_recommendations`
172 rows (55 BUY / 113 HOLD / 4 SELL):

| Workbook column | ORM field | Notes |
|---|---|---|
| `Rating` | `rating` | `CIORating` enum; values match exactly |
| `Rating Since` | `rating_since` | Excel serial → `excel_serial_to_date` |
| `Asset Class` | `asset_class` | |
| `Sub-Asset Class` | `sub_asset_class` | |
| `Region` | `region` | |
| `Industry Group` | `industry_group` | |
| `Issuer / Asset` | `issuer` | |
| `Security / Details` | `security` | |
| `ISIN` | `isin` | |
| `CIO View` | `cio_view` | citeable rationale for G2 traceability |
| `Valor` | `valor` | |
| `MIC` | `mic` | |
| `Yahoo Ticker` | `yahoo` | |
| `As Of` | `as_of` | Excel serial → `excel_serial_to_date` |
| *(computed)* | `is_swap_candidate` | True if `rating == BUY` AND ISIN not in any sample portfolio |

Upsert key: `isin` (unique per instrument; null for cash — treated as insert-only).
For idempotent reload: DELETE all `cio_recommendations` then bulk-insert (cleaner than
partial upsert given 172 rows with no partial-update semantics needed).

#### `Sample Portfolio {Defensive,Balanced,Growth}` → `clients` + `positions`
3 seed clients are upserted (by name) before positions are loaded:
- `"Sample Defensive"` → `mandate=DEFENSIVE`
- `"Sample Balanced"` → `mandate=BALANCED`
- `"Sample Growth"` → `mandate=GROWTH`

TASK-009 creates the real 4 persona clients (Räber / Schneider / Huber / Ammann) and will
assign them the correct mandate; at that point their positions can reference these seed rows
OR TASK-009 links them with fresh inserts. The seed clients are the immediate FK target.

| Workbook column | ORM field | Notes |
|---|---|---|
| `Asset Class` | `asset_class` | |
| `Sub-Asset Class` | `sub_asset_class` | |
| `Region` | `region` | |
| `Industry Group` | `industry_group` | |
| `Issuer / Asset` | `issuer` | |
| `Security / Details` | `security` | |
| `ISIN` | `isin` | |
| `Target (CHF)` | `target_chf` | |
| `Current (CHF)` | `current_chf` | drift input for ±2pp rule |
| `Valor` | `valor` | |
| `MIC` | `mic` | |
| `Yahoo Ticker` | `yahoo` | |
| *(null)* | `quantity` | populated later by TASK-026 holdings enrichment |

Idempotent reload: DELETE all positions for the 3 seed clients, then re-insert.
Client upsert: `INSERT ... ON CONFLICT (name) DO NOTHING`.

### Dependencies Required
- **Frontend packages:** none (backend-only seed).
- **Backend packages:** none to add — ORM models (SQLAlchemy), xlsx parser, and asyncpg are
  already in `requirements.txt`. Pure async SQLAlchemy inserts.
- **Database migrations:** none new — all 4 target tables exist (TASK-004). If a unique
  constraint on `clients.name` is absent, add it in a migration `0002_client_name_unique.py`
  (check `0001_initial_schema.py` first — `name` is NOT UNIQUE there; needs 0002).
- **Docker services:** requires `postgres` (already up via `depends_on` in compose).
- **Data mount:** the `data/` directory must be mounted into the backend container. Add a
  `data_dir` setting to `config.py` (`DATA_DIR` env var, default `/app/data`) and mount
  `./data:/app/data:ro` in docker-compose.yml.

### Impact Assessment

#### Files to Create
- `backend/app/loaders/__init__.py` — empty package init.
- `backend/app/loaders/portfolio.py` — the main async loader (see design below).
- `backend/app/routers/admin.py` — `POST /admin/seed/portfolio` endpoint (idempotent,
  returns counts of upserted rows).
- `backend/migrations/versions/0002_client_name_unique.py` — adds `UNIQUE` constraint on
  `clients.name` (enables upsert-by-name for seed clients and persona deduplication).

#### Files to Modify
- `backend/app/config.py` — add `data_dir: str = Field(default="/app/data")`.
- `backend/app/main.py` — `app.include_router(admin.router)`.
- `backend/docker-compose.yml` — add `./data:/app/data:ro` volume to the `backend` service.

#### Components Affected
- `mandate_strategies` table: **HIGH (new data)** — first write; 36 rows (12 sub-asset-classes × 3 mandates).
- `cio_recommendations` table: **HIGH (new data)** — first write; 172 rows.
- `positions` table: **HIGH (new data)** — first write; ~30–40 rows per portfolio (~90–120 total).
- `clients` table: **HIGH (new data)** — 3 seed clients.
- TASK-022 (drift detect): **HIGH dependency** — reads `positions.current_chf` / `target_chf`
  and `mandate_strategies.target_weight`; TASK-008 must load these correctly first.
- TASK-021 (swap engine): **HIGH dependency** — reads `cio_recommendations` filtered by
  `rating=BUY` and `is_swap_candidate=True` + `industry_group` match.
- TASK-026 (holdings-enrich): **MEDIUM dependency** — reads positions for SIX lookup by
  `valor` + `mic`; adds `quantity` field this task leaves null.

#### API Changes
- New endpoint: `POST /admin/seed/portfolio` → `{loaded: {mandate_strategies: int, cio_recommendations: int, positions: int, clients: int}}`.
- No changes to existing endpoints.

#### Database Changes
- New migration `0002`: `ALTER TABLE clients ADD CONSTRAINT uq_clients_name UNIQUE (name)`.
- First data written to `mandate_strategies`, `cio_recommendations`, `positions`, `clients`.
- Idempotent: DELETE+INSERT for positions/CIO rows; upsert-by-name for clients; upsert-by-key for mandate_strategies.

### Loader Module Design (`backend/app/loaders/portfolio.py`)

```python
# Three async functions, composed by load_all():
async def load_mandate_strategies(session, rows) -> int
async def load_cio_recommendations(session, rows) -> int
async def load_sample_portfolios(session, defensive, balanced, growth) -> int
async def load_all(data_dir: str) -> dict[str, int]
```

Key decisions:
- **All inserts are async** via SQLAlchemy `session.execute(insert(...))` / `session.merge()`.
- **Idempotency**: mandate_strategies uses `on_conflict_do_update` (unique index exists);
  clients uses `on_conflict_do_nothing` (after 0002 migration); CIO rows and positions use
  DELETE-then-insert (simpler and correct for reload semantics).
- **`is_swap_candidate`**: computed after loading all 3 sample portfolios — collect all
  held ISINs, then mark CIO BUY rows where `isin NOT IN held_isins`.
- **Date conversion**: `excel_serial_to_date` from `app.xlsx` for `Rating Since` and `As Of`.
- **Numeric coercion**: `float(value)` for CHF and weight columns; guard `None` cells.
- **Enum mapping**: `Mandate["DEFENSIVE"]` / `CIORating["BUY"]` (by name, matching PG enum).
- **Logging**: `log.info("loader.portfolio.done", ...)` — structured, matching app conventions.

### Implementation Checklist
- [ ] Add `0002_client_name_unique.py` migration; smoke-test `upgrade head` / `downgrade`
- [ ] Add `data_dir` to `Settings`; add `./data:/app/data:ro` mount to docker-compose.yml
- [ ] Create `app/loaders/__init__.py` + `app/loaders/portfolio.py`
- [ ] `load_mandate_strategies`: 12 sub-asset-classes × 3 mandates = 36 upserts
- [ ] `load_cio_recommendations`: 172 rows; excel serial → date for Rating Since / As Of
- [ ] `is_swap_candidate` computation: BUY rows with ISIN not in any sample portfolio
- [ ] `load_sample_portfolios`: upsert 3 seed clients; DELETE+INSERT positions per client
- [ ] Create `app/routers/admin.py` with `POST /admin/seed/portfolio`
- [ ] Register admin router in `app/main.py`
- [ ] Manual smoke-test: call endpoint, verify row counts in psql
- [ ] Idempotency test: call endpoint twice, assert same counts / no duplicates
- [ ] Follow SOLID principles; reuse `xlsx.py` and `db.SessionFactory`; no duplicate logic

### Risk Analysis
- **Risk Level:** MEDIUM
- **Main Risks:**
  - *Missing `clients.name` UNIQUE constraint* — upsert-by-name fails without 0002 migration.
    Mitigation: write 0002 first; test `alembic upgrade head` round-trip before the loader.
  - *`data/` not mounted in container* — loader raises `FileNotFoundError`.
    Mitigation: add volume to docker-compose.yml and `data_dir` to config in same commit.
  - *Null / blank cells in workbook* — e.g. some positions have `MIC=None` (Roche Genussschein
    verified in live parse). Mitigation: guard all numeric/date coercions for `None`.
  - *`is_swap_candidate` join logic wrong* — BUY candidates incorrectly flagged.
    Mitigation: collect held ISINs set from all 3 portfolios before updating CIO rows;
    verify counts against known values (55 BUY; ~subset should be not-held).
  - *Async SQLAlchemy dialect quirks with `on_conflict_do_update`* — asyncpg dialect requires
    explicit column list in `set_` clause. Mitigation: use standard dialect-aware syntax per
    SQLAlchemy 2.0 docs.

### Estimated Effort
- Original: **M**
- Adjusted: **M** — four loader functions + one migration + one admin endpoint + compose
  volume. The schema contract is fully defined; the column mapping is confirmed by live parse.
  Main complexity is the async SQLAlchemy upsert patterns and the `is_swap_candidate` join.

---

## Implementation (2026-06-20)

**Files created**
- `backend/migrations/versions/0002_client_name_unique.py` — `UNIQUE` constraint on
  `clients.name`; enables upsert-by-name for seed clients and persona dedup (TASK-009).
- `backend/app/loaders/portfolio.py` — async portfolio loader: `load_mandate_strategies`
  (upsert 39 rows), `_load_sample_portfolios` (3 seed clients + 207 positions via
  delete-and-reload), `_collect_held_isins`, `_load_cio_recommendations` (172 rows,
  `is_swap_candidate` computed from held-ISIN cross-reference).
- `backend/app/routers/admin.py` — added `POST /admin/seed/portfolio` endpoint matching the
  existing CRM seed pattern (Depends(get_session), HTTPException 500 on error).

**Files modified**
- `backend/app/models/source.py` — fixed `CIORecommendation.rating` to use
  `SAEnum(CIORating, name="cio_rating", create_type=False)`. Bug: SQLAlchemy auto-generates
  type name `ciorating` from the class name but the migration created the PG type as
  `cio_rating`; the mismatch produced a runtime `UndefinedObjectError` on first INSERT.
- `backend/app/models/derived.py` — same fix applied proactively to all multi-word enum
  columns (`DraftStatus→draft_status`, `ActionType→action_type`, `AlertStatus→alert_status`,
  `ExecutionMode→execution_mode`, `TaskStatus→task_status`) to prevent identical failures
  in TASK-032/049/etc.

**Verified live** (`docker compose restart backend` → migration 0001→0002 logged →
`POST /admin/seed/portfolio` → `{"status":"ok","loaded":{"mandate_strategies":39,
"clients":3,"positions":207,"cio_recommendations":172}}`):
- Second call returns identical counts (idempotent ✓)
- `is_swap_candidate`: 31 BUY-not-held / 24 BUY-held / 113 HOLD / 4 SELL ✓
- `target_chf` + `current_chf` both loaded for drift (TASK-022) ✓

**Note** — `mandate_strategies` shows 39 rows (not 36): the workbook has 13 sub-asset-class
rows (not 12 as documented in §10.2). All three mandates have a "Alternatives" row.

Ready for `/review-task`.
