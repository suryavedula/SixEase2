# TASK-020: Fit-score model

**Status:** IN-PROGRESS · **Epic:** EPIC-05 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Deterministic, explainable per-holding and per-portfolio fit score from DNA exclusions/tilts vs instrument tags; value-weighted aggregate. LLM may narrate but not produce the score.

## Acceptance Criteria
- [ ] per-holding and portfolio fit computed
- [ ] score breakdown explains each contribution
- [ ] deterministic and reproducible

## Dependencies
TASK-010 (**done** — `enriched_holdings.tags` JSONB populated for all positions; `cio_recommendations.tags` populated for all 172 CIO rows; `instrument_tags()` in `app/tags.py`)
TASK-016 (**done** — `client_dna.exclusions` and `client_dna.tilts` JSONB arrays fully extracted for all 4 real personas; each item carries `{text, tag, source_note_ids, confidence}`)

## Refs
Requirements §11 E7

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **`enriched_holdings.fit_score` (Float)** (`models/derived.py:85`) — write target for per-holding score; already in schema from migration 0001. No migration needed.
- **`enriched_holdings.conflicts` (JSONB)** (`models/derived.py:86`) — write target for per-holding score breakdown; already in schema from migration 0001. No migration needed.
- **`enriched_holdings.tags` (JSONB)** — `{sector, region, value_tags: [...]}` shape set by TASK-010 loader; TASK-020 reads `value_tags`.
- **`client_dna.exclusions` (JSONB)** — array of `{text, tag, source_note_ids, confidence}`; `tag` is from the shared vocabulary (VALID_TAGS in `app/loaders/dna.py`).
- **`client_dna.tilts` (JSONB)** — same shape; `tag` tokens to positively score.
- **`positions.current_chf` (Numeric)** (`models/source.py:76`) — CHF value for value-weighting the portfolio aggregate.
- **`ix_enriched_position` unique index on `position_id`** (`models/derived.py:88`) — guarantees one `enriched_holdings` row per position; used in the UPDATE join.
- **`instrument_tags()` in `app/tags.py`** — not needed by the scorer (tags are already stored), but `VALID_TAGS` set in `app/loaders/dna.py` is authoritative for the tag vocabulary.
- **`get_session` / `AsyncSession`** (`app/db.py`) — session dependency.
- **`get_logger`** (`app/logging.py`) — structured logging pattern.
- **Admin router pattern** (`app/routers/admin.py`) — `POST /admin/seed/fit` follows the exact pattern of `seed_tags` / `seed_dna`.
- **`GET /clients/{client_id}/dna` pattern** (`app/routers/dna.py`) — `GET /clients/{client_id}/portfolio/fit` follows the same read-endpoint pattern.
- **Synthetic clients** (`app/loaders/synthetic.py`) — `seed_synthetic` creates `EnrichedHolding` rows with tags for 100 synthetic clients. The fit scorer runs over ALL clients (or one), so synthetic clients are covered automatically. The scale-proof (§12 D4) is satisfied without special-casing.

### Scoring Algorithm (deterministic, no LLM)

**Constants (module-level, auditable):**
```python
BASE_SCORE = 0.5          # neutral holding — no exclusion, no tilt match
TILT_BONUS = 0.25         # per matched tilt tag (max two matches → 1.0)
EXCLUSION_SCORE = 0.0     # any exclusion match → score forced to 0.0
```

**Per-holding score:**
```python
def _score_holding(value_tags, exclusion_tag_set, tilt_tag_set):
    breakdown = []
    for tag in value_tags:
        if tag in exclusion_tag_set:
            breakdown.append({"tag": tag, "impact": "exclusion", "direction": -1})
        elif tag in tilt_tag_set:
            breakdown.append({"tag": tag, "impact": "tilt", "direction": +1})
    
    if any(b["impact"] == "exclusion" for b in breakdown):
        return 0.0, breakdown
    tilt_hits = sum(1 for b in breakdown if b["impact"] == "tilt")
    score = min(1.0, BASE_SCORE + tilt_hits * TILT_BONUS)
    return score, breakdown
```

Score semantics:
- `1.0` = two or more tilt tags match (strongly aligned)
- `0.75` = one tilt tag match (positively aligned)
- `0.5` = neutral (no tilt, no exclusion)
- `0.0` = any exclusion match (instrument violates a hard red line)

**Portfolio aggregate (value-weighted):**
```python
portfolio_fit = sum(p.current_chf * eh.fit_score for p, eh in pairs) / sum(p.current_chf for p, eh in pairs)
```
Computed in the read endpoint on-the-fly (all inputs are in the DB); not stored separately.

### Dependencies Required

- **Frontend packages:** none (backend-only)
- **Backend packages:** none new — SQLAlchemy, asyncpg already present
- **Database migrations:** none — `fit_score` and `conflicts` already exist in `enriched_holdings` (migration 0001)
- **Docker services:** `postgres` (must be running)
- **Seeding order:** `seed/portfolio` → `seed/tags` → `seed/dna` → `seed/fit`

### Impact Assessment

#### Files to Create
- `backend/app/loaders/fit.py` — `compute_fit(session, client_id=None) → dict` scoring engine
- `backend/app/routers/portfolio.py` — `GET /clients/{client_id}/portfolio/fit` read endpoint

#### Files to Modify
- `backend/app/routers/admin.py` — add `POST /admin/seed/fit`; update module docstring
- `backend/app/main.py` — `include_router(portfolio.router)`

#### Components Affected
- `enriched_holdings.fit_score`: **HIGH (first write)** — TASK-020 computes and stores all per-holding scores
- `enriched_holdings.conflicts`: **HIGH (first write)** — TASK-020 stores the breakdown JSON
- TASK-021 (swap engine): **HIGH dependency** — reads `fit_score` to compute `fit_gain` for swap proposals
- TASK-028 (news/alerts): **MEDIUM** — no direct dependency; scores exposed via the read endpoint
- Frontend DNA widgets (TASK-019): **MEDIUM** — can consume the new `GET /clients/{client_id}/portfolio/fit` endpoint once mounted

#### API Changes
- New: `POST /admin/seed/fit` → `{"status": "ok", "loaded": {"clients_scored": 4, "holdings_scored": 207}}`
  - Optional `?client_id=<uuid>` to score one client
- New: `GET /clients/{client_id}/portfolio/fit` → `PortfolioFitResponse` (see Module Design)
- No changes to existing endpoints.

#### Database Changes
- Writes `fit_score` (Float) to all `enriched_holdings` rows for scored clients
- Writes `conflicts` (JSONB) to all `enriched_holdings` rows for scored clients
- No schema changes; no new migrations.

### Module Design

#### `backend/app/loaders/fit.py`
```python
# Public API:
#   compute_fit(session, client_id=None) → dict[str, Any]
#     Scores all clients (or one). Returns {"clients_scored": N, "holdings_scored": N}.
#
# Constants: BASE_SCORE=0.5, TILT_BONUS=0.25, EXCLUSION_SCORE=0.0
#
# _score_holding(value_tags, exclusion_tag_set, tilt_tag_set) → (float, list[dict])
#   Deterministic; no side effects; no LLM call.
#
# compute_fit():
#   1. SELECT clients (optionally filtered)
#   2. For each client: SELECT ClientDNA → build exclusion_tag_set, tilt_tag_set
#      (extract only the `tag` field from each JSONB item; skip nulls)
#   3. SELECT Position JOIN EnrichedHolding ON position_id=positions.id WHERE client_id=X
#   4. For each (position, holding) pair:
#        value_tags = holding.tags["value_tags"] if holding.tags else []
#        score, breakdown = _score_holding(value_tags, exclusion_tag_set, tilt_tag_set)
#        UPDATE enriched_holdings SET fit_score=score, conflicts=breakdown WHERE id=holding.id
#   5. Commit once per client (same pattern as extract_dna)
#   6. Log fit.client_scored with holding count and portfolio score
```

#### `backend/app/routers/portfolio.py`
```python
class HoldingFit(BaseModel):
    position_id: str
    issuer: str | None
    security: str | None
    industry_group: str | None
    current_chf: float | None
    tags: dict | None           # full {sector, region, value_tags} payload
    fit_score: float | None
    conflicts: list | None      # breakdown items

class PortfolioFitResponse(BaseModel):
    client_id: str
    client_name: str
    mandate: str
    portfolio_fit: float | None   # value-weighted aggregate (computed on read)
    holdings: list[HoldingFit]
    total_holdings: int
    scored_holdings: int          # holdings with fit_score not null

# GET /clients/{client_id}/portfolio/fit
# Joins Position + EnrichedHolding for the client; computes portfolio_fit in Python.
# Returns 404 if client not found; returns scored=0 gracefully if seed/fit hasn't run.
```

### Implementation Checklist
- [ ] Write `backend/app/loaders/fit.py`: constants, `_score_holding()`, `compute_fit(session, client_id=None)`
- [ ] Reuse `enriched_holdings.tags["value_tags"]` — already stored; no call to `instrument_tags()` needed
- [ ] Extract exclusion/tilt tags: `{item["tag"] for item in dna.exclusions if item.get("tag")}` — handles nulls
- [ ] Handle `holding.tags is None` gracefully: treat as empty tag list (score = 0.5, no conflicts)
- [ ] Handle `position.current_chf is None` in portfolio aggregate: skip from weighting (treat as 0)
- [ ] Commit once per client (same as `extract_dna`) — partial failure recoverable
- [ ] Write `backend/app/routers/portfolio.py` with `GET /clients/{client_id}/portfolio/fit`
- [ ] Add `POST /admin/seed/fit` to `admin.py` following exact pattern of `seed_dna`
- [ ] Wire `portfolio.router` into `main.py`
- [ ] Smoke-test: call `seed/fit`, verify `enriched_holdings.fit_score` not null for 207 rows
- [ ] Idempotency test: call `seed/fit` twice, assert scores unchanged for same inputs
- [ ] Verify determinism: Räber — IT+USA positions must score 0.0 (us-tech exclusion); Energy must score 0.0 for Huber; Utilities must score 0.75 for Huber (sustainability tilt)
- [ ] Scale proof: `seed/synthetic` + `seed/fit` — verify 100 synthetic clients all scored
- [ ] Follow SOLID: `fit.py` has no FastAPI imports; pure async service function; no LLM calls
- [ ] Write self-documenting code; no comments repeating what the code does

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - *`enriched_holdings` row missing for a position* — `load_tags` (TASK-010) creates/upserts one row per position, so rows should exist. Mitigation: skip and log a warning if `EnrichedHolding` is absent for a position; do not crash.
  - *`client_dna` row missing* — `seed/fit` called before `seed/dna`. Mitigation: raise `RuntimeError` if no DNA found for a client, same as `extract_dna` pattern for missing interactions.
  - *`tags` JSONB is NULL* — `seed/fit` called before `seed/tags`. Mitigation: treat as empty tag list (score = 0.5); log a warning per holding; do not crash.
  - *Portfolio aggregate with all-null `current_chf`* — could divide by zero. Mitigation: guard `total_chf > 0`; return `None` for portfolio_fit if no CHF values available.
  - *Synthetic client count* — 100 synthetic × ~50 positions each = 5,000 `enriched_holdings` updates. Still fast (bulk UPDATE in a single transaction per client, no LLM latency). No risk.

### Estimated Effort
- Original: **M**
- Adjusted: **S** — all data is already in the DB (tags + DNA); the scorer is pure Python arithmetic; both schema columns exist; the router pattern is established. Main work is wiring the JOIN, the scoring loop, and the read endpoint.
