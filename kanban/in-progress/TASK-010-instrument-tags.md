# TASK-010: Instrument value-tagging layer

**Status:** IN-PROGRESS · **Epic:** EPIC-02 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Annotate every instrument (holdings + CIO universe) with region, sector, and value/controversy tags (us-tech, fossil, deforestation-risk, neuro-research, labour-risk, luxury, etc.) to enable DNA matching.

## Acceptance Criteria
- [ ] each instrument carries region+sector+value tags
- [ ] tag vocabulary documented
- [ ] curated map covers the demo personas conflicts

## Dependencies
TASK-008 (**done** — positions + CIO recommendations loaded; `enriched_holdings.tags` JSONB already in schema)

## Refs
Requirements §11 E5, E6

---

## Technical Analysis (Auto-generated 2026-06-20)

### Dependency Status
- **TASK-008** — in `in-progress/`, fully implemented and verified live:
  207 positions across 3 seed clients, 172 CIO rows, 39 mandate strategies loaded.
  `enriched_holdings.tags JSONB` already exists in the schema (migration 0001).
  The comment in `derived.py` (line 67–69) explicitly reads: *"Tags live here as JSONB
  until the normalised instrument-tag table (TASK-010) exists"* — so TASK-010 is the
  intended owner of creating `enriched_holdings` rows and filling their `tags`.

### Existing Resources Found
- **`enriched_holdings.tags JSONB`** (migration 0001, `models/derived.py:77`) — already
  designed for this task. TASK-010 creates/upserts `EnrichedHolding` rows per position
  (one-to-one via `ix_enriched_position` unique index) and writes `tags` there.
- **`cio_recommendations.region` + `.industry_group` + `.sub_asset_class`** — region and
  sector are already on the CIO row; only `value_tags` is missing. A new `tags JSONB`
  column on `cio_recommendations` (migration 0003) stores the full tag payload there too.
- **`positions.region` + `.industry_group`** — same: already present; used as lookup keys
  into the static tag map.
- **`app/loaders/portfolio.py`** — `load_portfolio` pattern to reuse for the tag loader
  structure (async, one commit, returns row counts).
- **`app/routers/admin.py`** — exact endpoint pattern to follow for `POST /admin/seed/tags`.
- **`app/models/source.py`** — `CIORecommendation` ORM to extend with `tags` mapped column.
- **`app/db.py`** — `get_session`, `SessionFactory` for the loader and endpoint.
- **`app/logging.py`** — `get_logger` for structured log output.

### Tag Vocabulary (E5 — documented)

Keyed by `industry_group` (the E3 swap match key), with region-qualified overrides.

#### Base tags by industry group

| Industry Group | value_tags |
|---|---|
| `Information Technology` | `["tech"]` |
| `Communication Services` | `["tech", "media"]` |
| `Energy` | `["fossil", "fossil-fuel"]` |
| `Materials` | `["deforestation-risk", "labour-risk"]` |
| `Health Care` | `["pharma", "neuro-research"]` |
| `Consumer Discretionary` | `["luxury", "labour-risk"]` |
| `Consumer Staples` | `["luxury"]` |
| `Digital Assets` | `["crypto"]` |
| `Utilities` | `["sustainability"]` |
| `Diversified ETF` | `["sustainability", "diversified"]` |
| `Financials` | `[]` |
| `Government Bonds` | `[]` |
| `Investment Grade` | `[]` |
| `Industrials` | `[]` |
| `Telecommunication` | `[]` |
| `Real Estate (Fund)` | `[]` |
| `Real Estate (REIT)` | `[]` |
| `Precious Metals` | `[]` |
| `Private Markets` | `[]` |

#### Region-qualified overrides (applied on top of base tags)

| (industry_group, region) | extra_tags |
|---|---|
| `("Information Technology", "USA")` | `["us-tech"]` |
| `("Communication Services", "USA")` | `["us-tech"]` |

#### Tag semantics (E6 alignment)

| Tag | Used by | Exclusion / Tilt |
|---|---|---|
| `us-tech` | Räber | **exclude** (defensive value, avoid US concentration) |
| `fossil` / `fossil-fuel` | Huber | **exclude** (ESG / sustainable-agriculture persona) |
| `deforestation-risk` | Huber | **exclude** (palm-oil / timber exposure) |
| `pharma` | Schneider | **exclude** (pharma companies that defund neuro research) |
| `neuro-research` | Schneider | **tilt** (Parkinson's / CNS research focus) |
| `labour-risk` | Ammann | **exclude** (corporate-reputation persona) |
| `luxury` | Ammann | **tilt** (quality / luxury consumer brands) |
| `tech` | general | sector label, no per-persona exclusion |
| `sustainability` | Huber | **tilt** (ESG-aligned instruments) |
| `crypto` | general | asset-class label |

_Note: `pharma` and `neuro-research` are both applied to Health Care because the Schneider
persona's conflict is "pharma that defunds neuro research" — the DNA-matching layer
(TASK-016/020) combines these two tags to evaluate fit; a Health Care instrument with
`pharma` but no `neuro-research` association is safe for Schneider._

### Persona Coverage Check

| Persona | Mandate | Exclusions → tags matched | Tilts → tags matched |
|---|---|---|---|
| Räber | DEFENSIVE | `us-tech` → IT + USA ✓ | Swiss/European quality → no-us-tech positions ✓ |
| Huber | BALANCED | `fossil`, `deforestation-risk` → Energy, Materials ✓ | `sustainability` → Utilities, ETF ✓ |
| Ammann | GROWTH | `labour-risk` → Materials, Consumer Disc. ✓ | `luxury` → Consumer Disc./Staples (Richemont, Lindt, Nestlé) ✓ |
| Schneider | BALANCED | `pharma` → Health Care ✓ | `neuro-research` → Health Care ✓ |

### Dependencies Required
- **Frontend packages:** none (backend-only)
- **Backend packages:** none new — SQLAlchemy, asyncpg already in `requirements.txt`
- **Database migrations:** `0003_cio_tags.py` — `ALTER TABLE cio_recommendations ADD COLUMN tags JSONB`
- **Docker services:** `postgres` (already up)
- **Data dependency:** `enriched_holdings` rows require `positions` rows (TASK-008 ✓);
  `cio_recommendations` rows require portfolio seed (TASK-008 ✓)

### Impact Assessment

#### Files to Create
- `backend/app/tags.py` — static `INDUSTRY_TAGS`, `REGION_EXTRA_TAGS`, and `instrument_tags(industry_group, region) → dict`
- `backend/app/loaders/tags.py` — `load_tags(session) → dict[str, int]`
- `backend/migrations/versions/0003_cio_tags.py` — adds `tags JSONB` to `cio_recommendations`

#### Files to Modify
- `backend/app/models/source.py` — add `tags: Mapped[dict | None] = mapped_column(JSONB)` to `CIORecommendation`
- `backend/app/routers/admin.py` — add `POST /admin/seed/tags` endpoint; update module docstring

#### Components Affected
- `enriched_holdings` table: **HIGH (first write)** — TASK-010 creates all 207 rows
- `cio_recommendations` table: **HIGH (schema change + data)** — adds `tags` column, populates 172 rows
- TASK-016 (DNA builder): **HIGH dependency** — reads `enriched_holdings.tags` for DNA-vs-holding fit scoring
- TASK-020 (fit scorer): **HIGH dependency** — compares `client_dna.exclusions/tilts` against `tags`
- TASK-021 (swap engine): **HIGH dependency** — filters swap candidates by tag exclusions (E6)
- TASK-028 (news matching): **MEDIUM dependency** — uses `tags` to route news to DNA themes

#### API Changes
- New: `POST /admin/seed/tags` → `{"status": "ok", "loaded": {"positions_tagged": 207, "cio_tagged": 172}}`
- No changes to existing endpoints.

#### Database Changes
- Migration 0003: `ALTER TABLE cio_recommendations ADD COLUMN tags JSONB`
- First data written to `enriched_holdings` (all positions get a row with `tags` set)
- `cio_recommendations.tags` populated for all 172 rows

### Module Design

#### `backend/app/tags.py`
```python
INDUSTRY_TAGS: dict[str, list[str]] = { ... }   # 19 industry groups → base value_tags
REGION_EXTRA_TAGS: dict[tuple[str, str], list[str]] = { ... }  # (ig, region) → extra

def instrument_tags(industry_group: str | None, region: str | None) -> dict:
    """Returns {"sector": ig, "region": region, "value_tags": [...]}."""
```

#### `backend/app/loaders/tags.py`
```python
async def load_tags(session: AsyncSession) -> dict[str, int]:
    """
    1. Query all positions with their industry_group and region
    2. Upsert enriched_holdings rows (on_conflict_do_update on position_id) setting tags
    3. UPDATE cio_recommendations SET tags = ... for each row (bulk update by isin or id)
    4. Single commit; return {"positions_tagged": N, "cio_tagged": N}
    """
```

Key decisions:
- `enriched_holdings` upsert uses `on_conflict_do_update` on `position_id` unique index —
  safe whether rows exist or not; does NOT touch `live_price`, `fit_score`, `conflicts`
  (those columns belong to later tasks).
- CIO tags: bulk UPDATE via SQLAlchemy `update(CIORecommendation).where(...).values(tags=...)`
  grouped by (industry_group, region) — avoids N=172 individual statements.
- Both operations are idempotent: running twice produces the same result.

### Implementation Checklist
- [ ] Write `backend/app/tags.py` with full `INDUSTRY_TAGS` dict covering all 19 groups
- [ ] Write `backend/migrations/versions/0003_cio_tags.py`; test `alembic upgrade head`
- [ ] Add `tags JSONB` mapped column to `CIORecommendation` in `source.py`
- [ ] Write `backend/app/loaders/tags.py` — `load_tags(session)`
- [ ] Add `POST /admin/seed/tags` to `admin.py`
- [ ] Smoke-test: call endpoint, verify `enriched_holdings` row count = 207, `cio_recommendations.tags` not null on 172 rows
- [ ] Idempotency test: call twice, assert counts unchanged
- [ ] Verify persona conflicts: query IT+USA → expect `us-tech`; Energy → expect `fossil`; Health Care → expect `pharma`+`neuro-research`
- [ ] Reuse `instrument_tags()` from `app/tags.py`; no duplicate tag logic in the loader
- [ ] Follow SOLID principles; no comments explaining what the code does

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - *Migration 0003 runs before model has `tags` column* — alembic runs before app imports;
    same pattern as 0002. Mitigation: add ORM column and migration in same commit.
  - *`positions` rows not present when loader runs* — loader queries positions table; caller
    must run `seed/portfolio` first. Mitigation: document ordering in endpoint; 500 if empty.
  - *Neuro-research tagging too broad* — all Health Care gets `neuro-research`, which may flag
    non-pharma health instruments. Mitigation: acceptable for demo; DNA matcher (TASK-020) uses
    both tags together to score conflict, not either alone.
  - *CIO bulk UPDATE grouping* — grouping rows by (ig, region) for batch UPDATE requires
    collecting distinct groups first. Mitigation: collect via `SELECT DISTINCT` or a Python
    dict from already-loaded ORM rows.

### Estimated Effort
- Original: **M**
- Adjusted: **S–M** — the tag map is a static dict; the loader pattern is already established
  (TASK-008/009); migration is one column. Main work is authoring the curated tag map and
  wiring the upsert correctly for `enriched_holdings`.
