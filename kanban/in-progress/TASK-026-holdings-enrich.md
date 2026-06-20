# TASK-026: Holdings enrichment and live pricing

**Status:** IN-PROGRESS · **Epic:** EPIC-06 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Resolve each holding to SIX identifiers and value via live SIX data with graceful fallback to workbook Current (par-pricing for bonds); compute weights and drift; annotate entity ids + tags.

## Acceptance Criteria
- [ ] holdings valued live with fallback
- [ ] weights and drift computed (feeds E10)
- [ ] entity ids + tags attached (P4)

## Dependencies
TASK-013, TASK-008, TASK-010

## Refs
Requirements §13.1 P1-P5

---

## Technical Analysis (Auto-generated 2026-06-20)

### Dependency Status

| Task | Status | What it provides |
|---|---|---|
| TASK-013 (SIX client) | IN-PROGRESS — `backend/app/six.py` fully implemented and wired into `main.py` lifespan | `get_eod_snapshot(listing_id)`, `get_intraday_snapshot(listing_id)`, `resolve_by_isin(isin)` — all async, ready to call |
| TASK-008 (load portfolio) | IN-PROGRESS — verified live; 207 positions across 3 seed clients | `positions` table has `valor`, `mic`, `isin`, `yahoo`, `issuer`, `current_chf`, `target_chf`; `quantity` is NULL (reserved for TASK-026) |
| TASK-010 (instrument tags) | IN-PROGRESS — 207 `enriched_holdings` rows created, `tags` JSONB set | `enriched_holdings` rows already exist with `tags` set; `live_price` / `live_price_at` are NULL — these are the write targets |

All three dependencies are **materially satisfied** — proceeding.

### Existing Resources Found

- **`backend/app/six.py`** — full async SIX MCP client. TASK-026 calls `get_eod_snapshot("{valor}_{mic}")` per holding. SSE/JSON duality, NaN guard, ValueError on no close price all already handled.
- **`backend/app/models/derived.py:EnrichedHolding`** — already has `live_price: Numeric(15,8)` and `live_price_at: DateTime(timezone=True)` (migration 0001). Index `ix_enriched_position` on `position_id` (unique) enables the update/upsert.
- **`backend/app/models/source.py:Position`** — already has `quantity: Numeric(18,8)` (nullable, migration 0001). TASK-008 explicitly left it NULL for TASK-026.
- **`backend/app/loaders/tags.py`** — loader pattern to follow exactly: async, idempotent UPDATE on `enriched_holdings`, single commit per batch, returns `dict[str, int]` counts.
- **`backend/app/loaders/drift.py`** — per-client scoping pattern (`client_id: uuid.UUID | None = None`), commit-per-client for partial-failure safety.
- **`backend/app/routers/admin.py`** — established `POST /admin/seed/*` endpoint pattern; module docstring convention with TASK attribution.
- **`backend/app/routers/portfolio.py`** — existing `GET /clients/{id}/portfolio/fit` pattern to follow for the new live-weights read endpoint.

### SIX Identifier Flow

```
positions.valor + positions.mic  →  "{valor}_{mic}"  →  six.get_eod_snapshot()
                                                            ↓ success
                                           enriched_holdings.live_price = close
                                           enriched_holdings.live_price_at = timestamp
                                           positions.quantity = current_chf / close  (equities)
                                                            ↓ ValueError / network error
                                                        fallback_used++; live_price stays NULL
positions with NULL mic or valor  →  fallback immediately; try resolve_by_isin(isin) as bonus
Bond positions (by sub_asset_class) → skip SIX; live_price = NULL; quantity = current_chf / 100
```

### Scope Clarification: P4 Entity IDs

P4 (§13.1) says: "entity identifiers — issuer name + aliases, ticker, ISIN — for news matching."
These identifiers already exist on `positions` (`valor`, `mic`, `isin`, `yahoo`, `issuer`). TASK-027 (watchlist, next in chain) reads them directly. No new schema column needed. TASK-026's P4 contribution is: (1) confirming SIX resolution succeeds for each holding (valor+mic resolvable), and (2) making the enriched view available via the live endpoint so TASK-027 can build the watchlist from enriched data.

### Dependencies Required
- **Backend packages:** none new — `httpx`, SQLAlchemy, asyncpg in `requirements.txt`; `six.py` already wired in `main.py`
- **Database migrations:** none — `enriched_holdings.live_price` / `live_price_at` and `positions.quantity` are all in migration 0001

### Impact Assessment

#### Files to Create
- `backend/app/loaders/holdings.py` — `enrich_holdings(session, client_id=None) → dict[str, int]`

#### Files to Modify
- `backend/app/routers/admin.py` — add `POST /admin/seed/enrich`; update module docstring to include TASK-026
- `backend/app/routers/portfolio.py` — add `GET /clients/{client_id}/portfolio/live` (live price + weights + drift)

#### Components Affected
- `enriched_holdings` table: **HIGH** — writes `live_price` / `live_price_at` for 207 positions (seed clients)
- `positions` table: **MEDIUM** — writes `quantity` for each position
- TASK-027 (watchlist): **HIGH dependency** — depends on TASK-026 completing; reads `positions.valor`/`isin`/`issuer`
- TASK-022 (drift alerts): **LOW** — existing drift alert logic unchanged; uses `current_chf`; enrichment is additive
- Frontend (TASK-025 portfolio widgets): **MEDIUM** — `/portfolio/live` endpoint feeds drift-bar widget and live-price column

#### API Changes
- **New:** `POST /admin/seed/enrich` → `{"status": "ok", "loaded": {"live_priced": N, "fallback_used": N, "quantity_set": N}}`
- **New:** `GET /clients/{client_id}/portfolio/live` → per-holding live prices, sub-asset-class weights vs mandate targets, drift pp per SAC

#### Database Changes
- None (schema complete). Data: UPDATE `enriched_holdings.live_price` / `live_price_at`; UPDATE `positions.quantity`

### Module Design (`backend/app/loaders/holdings.py`)

```python
_BOND_SAC = frozenset({"Investment Grade", "Government Bonds", "Private Markets"})

async def enrich_holdings(session, client_id=None) -> dict[str, int]:
    """
    1. Query all clients (or scoped to one)
    2. Per position: bond? → par-price; has valor+mic? → SIX EOD; else → fallback
    3. UPDATE enriched_holdings SET live_price, live_price_at
    4. UPDATE positions SET quantity
    5. Commit per client; return counts
    """
```

Key decisions:
- **EOD over intraday**: `get_eod_snapshot` primary (settled, reliable). No intraday for hackathon — avoids market-hours coupling.
- **Per-client commit**: failure on client N doesn't roll back N-1.
- **SIX failure = warning, not abort**: `fallback_used` counter; endpoint returns 200.
- **Synthetic clients**: with ~100+ synthetic clients, SIX rate limits would be hit. Scope to real 4 persona clients only by default; synthetic clients use `current_chf` as-is.
- **Bond quantity**: CLAUDE.md: "bonds priced at par (qty = face ÷ 100)". Workbook `current_chf` is the CHF face value ÷ 100, so `quantity = current_chf` (i.e., one unit = CHF 100 face). Simplest: `quantity = current_chf / 100.0` (face units / 100).

### Implementation Checklist
- [ ] Write `backend/app/loaders/holdings.py` with `enrich_holdings()` and bond-detection heuristic
- [ ] Guard `valor` and `mic` NULL — skip or fallback; try `resolve_by_isin` if ISIN available
- [ ] `UPDATE positions SET quantity = ...` (bulk per client, not per-row loop for equities)
- [ ] `UPDATE enriched_holdings SET live_price = ..., live_price_at = ...` via `on_conflict_do_update`
- [ ] Add `POST /admin/seed/enrich` to `admin.py`; update module docstring
- [ ] Add `GET /clients/{id}/portfolio/live` to `portfolio.py` — returns holdings with `live_price`, `live_chf` (live_price × quantity), and SAC weight summary vs mandate target
- [ ] Smoke-test: call enrich, verify `enriched_holdings.live_price` set for equity positions
- [ ] Idempotency test: second call overwrites with same/updated prices; no new rows
- [ ] Reuse `app.six` only; no new HTTP; no duplicate SIX call logic
- [ ] Follow SOLID principles — one function = one responsibility

### Risk Analysis
- **Risk Level:** MEDIUM
- **Main Risks:**
  - **SIX NaN / ValueError on illiquid venues**: already guarded in `six.py` (raises `ValueError` on no-close). Mitigation: catch per-position, increment `fallback_used`, continue.
  - **NULL mic on some positions**: Roche Genussschein and similar have no MIC. Mitigation: guard `if valor and mic:` — fall back to ISIN resolution or workbook value.
  - **Synthetic client scale**: 100 synthetic clients × 69 positions each = 6 900 SIX calls. Will hit rate limits. Mitigation: in `enrich_holdings`, skip non-persona clients (filter by name or add a `is_synthetic` flag). Default to real 4 clients only for enrichment.
  - **Bond SAC string mismatch**: `_BOND_SAC` must match exactly what TASK-008 loaded. Verify against live `SELECT DISTINCT sub_asset_class FROM positions` before shipping.
  - **live_price_at timezone**: SIX returns ISO strings; normalize to UTC with `datetime.fromisoformat`.

### Estimated Effort
- Original: **M**
- Adjusted: **M** — SIX client ready; schema done; loader pattern established. Main complexity is bond heuristic, NULL-mic guard, and live weights endpoint. ~2–3 hours.

---

## Implementation (2026-06-20)

**Files created**
- `backend/app/loaders/holdings.py` — `enrich_holdings(session, client_id=None, skip_synthetic=True)`: iterates real-persona clients (skips `Synthetic%` names), calls `six.get_eod_snapshot("{valor}_{mic}")` per equity position, writes `enriched_holdings.live_price` + `live_price_at`, computes `positions.quantity` (bonds: `current_chf / 100`; equities: `current_chf / live_price`). Per-client commit, graceful SIX fallback (warning + counter).

**Files modified**
- `backend/app/routers/admin.py` — added `POST /admin/seed/enrich` endpoint; added `from app.loaders.holdings import enrich_holdings` import; updated module docstring.
- `backend/app/routers/portfolio.py` — added `LiveHolding`, `SacWeight`, `PortfolioLiveResponse` models and `GET /clients/{client_id}/portfolio/live` endpoint; computes per-holding live CHF (live_price × quantity or fallback to current_chf) + SAC weights vs mandate targets + drift pp with breach flag.

**Verified live** (port 18000):
- `POST /admin/seed/enrich` → `{"live_priced": 0, "fallback_used": 207, "quantity_set": 56, "clients_processed": 7}` (SIX token not set in dev — expected; 56 bond positions got par-quantity)
- Second call returns identical counts (idempotent ✓)
- `GET /clients/{id}/portfolio/live` → 71 holdings for Defensive client; SAC weights + drift computed correctly from workbook fallback values; bond par-pricing verified in DB: `quantity × 100 = current_chf` ✓
- Bond positions have `live_price = NULL`, equity positions have `quantity = NULL` (awaiting SIX token)
- Seeding order confirmed: `seed/portfolio → seed/tags → seed/enrich`

Ready for `/review-task`.
