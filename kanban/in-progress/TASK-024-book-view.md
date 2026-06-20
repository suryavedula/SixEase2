# TASK-024: Book view (scale)

**Status:** IN-PROGRESS · **Epic:** EPIC-05 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Aggregate per-client fit + a ranked swap-proposal queue across the whole book (incl. synthetic clients) to demonstrate personalization at scale from one fixed strategy.

## Acceptance Criteria
- [ ] book endpoint returns clients sorted by fit
- [ ] each client has its own proposal queue
- [ ] runs across ~100 synthetic clients

## Dependencies
TASK-011, TASK-021

## Refs
Requirements §12 D4

---

## Technical Analysis (Auto-generated 2026-06-20)

### Dependency Status

| Task | Status | Impact on TASK-024 |
|---|---|---|
| **TASK-011** (synthetic clients) | DONE | 100 synthetic clients exist in `clients` table with positions + DNA. `seed/synthetic` is live via `POST /admin/seed/synthetic`. |
| **TASK-021** (swap engine) | IN-PROGRESS (implemented) | `swap_proposals` table is populated by `compute_swaps()`; `GET /clients/{id}/portfolio/swaps` already exists. Note: E11 fires for most clients because all CIO BUY candidates in conflicting industry groups share the exclusion tag — proposals will populate once CIO data is augmented or real persona DNA is extracted. Engine logic is correct. |

**Conclusion:** Both dependencies are materially satisfied. `portfolio_fit` is already computable from `enriched_holdings.fit_score + positions.current_chf`; `swap_proposals` rows exist. TASK-024 can proceed.

### Existing Resources Found

- **`compute_fit()` / `_score_holding()`** (`app/loaders/fit.py`) — fit scores already written to `enriched_holdings.fit_score`. No re-computation needed at read time.
- **`compute_swaps()`** (`app/loaders/swap.py`) — swap proposals written to `swap_proposals.fit_gain`. Already sorted by fit_gain DESC.
- **`Client`, `Position`** (`app/models/source.py`) — clients table has ~107 rows (4 personas + 3 sample + 100 synthetic).
- **`EnrichedHolding`, `SwapProposal`** (`app/models/derived.py`) — all columns needed for book aggregation.
- **`portfolio.router`** (`app/routers/portfolio.py`) — per-client `/portfolio/fit` and `/portfolio/swaps` pattern to follow. Router prefix, response model, and graceful-empty patterns established.
- **`app/main.py`** — `portfolio.router` already registered; `book.router` needs one `include_router` line.
- **`apiGet<T>` / `dna.ts`** (`frontend/src/api/`) — exact pattern for the new `book.ts` API module.

### Dependencies Required

- **Frontend packages:** none new
- **Backend packages:** none new — SQLAlchemy, asyncpg already present
- **Database migrations:** none — all tables exist (migration 0001)
- **Docker services:** `postgres` must be running
- **Seeding order:** `seed/portfolio` → `seed/tags` → `seed/synthetic` → `seed/dna` → `seed/fit` → `seed/swap` (then book view has full data)

### Impact Assessment

#### Files to Create
- `backend/app/routers/book.py` — `GET /book` endpoint with mandate filter

#### Files to Modify
- `backend/app/main.py` — import `book` router + one `app.include_router(book.router)` line

#### Optional (thin but useful for demo)
- `frontend/src/api/book.ts` — typed fetch module following `dna.ts` pattern

#### Components Affected
- `clients` table: **READ-ONLY** — no writes
- `positions` table: **READ-ONLY** — aggregated via SQL GROUP BY
- `enriched_holdings` table: **READ-ONLY** — `fit_score` aggregated per client
- `swap_proposals` table: **READ-ONLY** — top-3 per client fetched
- Existing per-client `/portfolio/fit` and `/portfolio/swaps` endpoints: **unaffected**

#### API Changes
- New: `GET /book?mandate=BALANCED` → `BookResponse` (see Module Design below)
- No changes to existing endpoints.

#### Database Changes
- None. No migrations required.

### Module Design

#### `backend/app/routers/book.py`

```python
GET /book
Query params:
  mandate: str | None  # optional: DEFENSIVE / BALANCED / GROWTH

Response: BookResponse
  total_clients: int
  scored_clients: int          # clients with ≥1 scored holding
  clients: list[BookClient]    # sorted by portfolio_fit DESC, nulls last

BookClient:
  client_id: str
  client_name: str
  mandate: str
  portfolio_fit: float | None  # value-weighted CHF; None if seed/fit not run
  total_positions: int
  conflict_positions: int      # positions where fit_score == 0.0
  proposal_count: int
  top_swaps: list[BookSwapSummary]  # up to 3, ranked by fit_gain DESC

BookSwapSummary:
  position_id: str
  from_security: str | None
  to_security: str | None      # candidate_valor or candidate_isin
  fit_gain: float | None
  dna_reason: str | None
```

**Query strategy (avoids N+1 across 107 clients):**

1. **Fit aggregate query** — single `SELECT + GROUP BY` across all clients:
   ```sql
   SELECT clients.id, clients.name, clients.mandate,
     COUNT(p.id)                                          AS total_positions,
     SUM(CASE WHEN eh.fit_score IS NOT NULL
              THEN p.current_chf * eh.fit_score ELSE 0 END)
     / NULLIF(SUM(CASE WHEN eh.fit_score IS NOT NULL
                       THEN p.current_chf ELSE 0 END), 0) AS portfolio_fit,
     SUM(CASE WHEN eh.fit_score = 0.0 THEN 1 ELSE 0 END) AS conflict_positions
   FROM clients
   LEFT JOIN positions p ON p.client_id = clients.id
   LEFT JOIN enriched_holdings eh ON eh.position_id = p.id
   [WHERE clients.mandate = :mandate]
   GROUP BY clients.id, clients.name, clients.mandate
   ```

2. **Proposals query** — fetch all proposals once; group + top-3 in Python:
   ```sql
   SELECT sp.holding_id, sp.candidate_valor, sp.candidate_isin, sp.fit_gain,
          sp.dna_reason, p.client_id, p.security AS from_security
   FROM swap_proposals sp
   JOIN positions p ON sp.holding_id = p.id
   [WHERE p.client_id IN (:ids)]
   ORDER BY p.client_id, sp.fit_gain DESC
   ```
   Group by `client_id` in Python; keep first 3 rows per client.

3. Sort result list by `portfolio_fit DESC nulls last` in Python before returning.

**Mandate filter:** convert query-param string to `Mandate` enum; return HTTP 422 via FastAPI validation if unrecognized value.

#### `frontend/src/api/book.ts`

Follows exact `dna.ts` pattern:
```typescript
export interface BookSwapSummary { ... }
export interface BookClient { ... }
export interface BookResponse { ... }
export function getBook(mandate?: string, signal?: AbortSignal): Promise<BookResponse> {
  const qs = mandate ? `?mandate=${mandate}` : "";
  return apiGet<BookResponse>(`/book${qs}`, signal);
}
```

### Implementation Checklist
- [ ] Create `backend/app/routers/book.py` with `GET /book`
- [ ] Single aggregate SQL for fit stats (no N+1 across 107 clients)
- [ ] Proposals fetched once per book call; grouped by client_id in Python
- [ ] Top 3 swap proposals per client, ranked by `fit_gain DESC`
- [ ] Mandate query param validated via Pydantic / FastAPI (optional, defaults to all clients)
- [ ] Sort result list by `portfolio_fit DESC` (nulls last) before returning
- [ ] `scored_clients` = count of clients where `portfolio_fit is not None`
- [ ] Add `from app.routers import book` + `app.include_router(book.router)` to `main.py`
- [ ] Create `frontend/src/api/book.ts` following `dna.ts` pattern
- [ ] Smoke-test: call `GET /book`, verify 107 rows returned, sorted correctly
- [ ] Verify mandate filter: `GET /book?mandate=BALANCED` returns only BALANCED clients
- [ ] Verify graceful: call before seed/fit → all `portfolio_fit=null`, no crash
- [ ] Follow SOLID: no LLM calls; pure read endpoint; no writes
- [ ] No duplicate logic — do not re-implement `_score_holding`; read existing `fit_score` column

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - *`proposal_count=0` for most clients (E11 constraint)*: The swap engine fires E11 for all current test cases because all CIO BUY IT candidates share the us-tech exclusion tag. Book view handles this correctly — `top_swaps=[]` is valid state, not an error. Will populate once real CRM DNA or richer CIO data is available. Mitigation: graceful empty already designed.
  - *`portfolio_fit=None` for real persona clients (Räber has no positions yet)*: Räber's `seed/fit` returns `fit.no_holdings`. Book view returns `portfolio_fit=None` and sorts Räber last. Mitigation: `nulls last` in Python sort.
  - *TASK-021 IN-PROGRESS*: The swap engine is fully implemented and the `seed/swap` endpoint is live. The only gap is data (E11), not logic. Book view has no code dependency on TASK-021 being "done" in kanban — the tables are already populated. Mitigation: none needed.
  - *Numeric overflow in fit aggregate*: CHF values are `Numeric(15,2)` columns; casting to Float in the aggregate is safe for the ~70 positions per client. Mitigation: cast explicitly in SQLAlchemy if needed.

### Estimated Effort
- Original: **M**
- Adjusted: **S** — all tables exist and are populated, patterns from `portfolio.py` are directly reusable, no migration, no new models. Main work is writing the aggregate SQL query and the response models.
