# TASK-023: Precedence, no-churn, no-swap handling

**Status:** IN-PROGRESS · **Epic:** EPIC-05 · **Priority:** P0 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20 · **Implementation Completed:** 2026-06-20

## Description
Apply constraint precedence (mandate > compliance > exclusion > CIO > soft); only propose when fit gain clears a threshold; when no candidate exists, keep and explain (maybe escalate as a moment).

## Acceptance Criteria
- [x] precedence ordering enforced
- [x] sub-threshold swaps suppressed (E12)
- [x] no-candidate produces explained keep (E11)

## Dependencies
TASK-021

## Refs
Requirements §11 E9/E11/E12

---

## Technical Analysis (Auto-generated 2026-06-20)

### Dependency Status
- **TASK-021** (swap engine) — IN-PROGRESS, fully implemented and live. `backend/app/loaders/swap.py`
  contains `compute_swaps()`, `FIT_GAIN_THRESHOLD = 0.0`, `_build_dna_reason()`, and partial E9/E11/E12
  handling. This is the file TASK-023 directly extends.

### What TASK-021 Already Implements (do NOT duplicate)
- Per-client conflict detection (`fit_score == 0.0`)
- CIO BUY candidate filtering (E3/E4): `is_swap_candidate=True`, same `sub_asset_class` + `industry_group`
- Per-client held-ISIN exclusion (E4)
- E9 exclusion guard: `candidate_score == 0.0 → skip` (candidate hits client hard exclusion tag)
- E12 stub: `fit_gain <= FIT_GAIN_THRESHOLD → skip` where threshold is currently `0.0`
- E11 stub: `log.warning("swap.no_compliant_candidate", ...)` — logs but does NOT write a keep record
- `SwapProposal` rows written with `mandate_neutral=True`, `sources` JSONB

### What TASK-023 Adds

#### 1. E9 — Explicit precedence (currently implicit)
The filter chain in `compute_swaps()` already applies the correct order but it's unnamed. TASK-023 makes
the five levels explicit with inline labels so the code is auditable:
```
P1 mandate:            sub_asset_class == position.sub_asset_class  (slot weight preserved, E1/E8)
P2 compliance:         industry_group == position.industry_group     (risk-neutral, same-sector, E3)
P3 hard exclusion:     candidate_score > 0.0                        (no client red line hit, E9)
P4 CIO universe:       is_swap_candidate=True, isin not in held     (BUY + not held, E4)
P5 soft optimization:  fit_gain > FIT_GAIN_THRESHOLD                (minimum value gain, E12)
```
No logic change — only explicit documentation in code via module-level docstring and inline comments.

#### 2. E12 — Meaningful threshold (currently 0.0)
`FIT_GAIN_THRESHOLD = 0.0` passes any positive gain. Change to `FIT_GAIN_THRESHOLD = 0.10`.

Rationale: in the current scoring model (base=0.5, tilt=+0.25, exclusion=0.0), any non-exclusion
candidate replaces a 0.0-scoring position with at least 0.5 gain, well above 0.10. The threshold
matters primarily for future soft-optimization swaps (non-conflict positions, fit_score > 0.0) where
marginal gains could be noise. Setting it now makes E12 machine-enforceable for that case.

The `<=` guard stays: `fit_gain <= FIT_GAIN_THRESHOLD → skip` (already correct).

#### 3. E11 — Keep record with explanation (currently just a log warning)
When no candidate survives the filter chain, TASK-021 only calls `log.warning(...)`. TASK-023 makes
this a **stored decision**: write a `SwapProposal` row with `candidate_isin=None` so the RM can see
"position X was reviewed, no viable swap exists, here's why."

Schema: no migration needed — `candidate_isin`, `candidate_valor`, `cio_view`, `fit_gain` are already
nullable. `dna_reason` carries the human-readable keep explanation. A `sources` entry with
`{"type": "keep_reason", "text": ...}` distinguishes it from a real proposal row.

Keep record shape:
```python
SwapProposal(
    holding_id=position.id,
    candidate_isin=None,
    candidate_valor=None,
    dna_reason=_build_keep_reason(all_candidates, exclusion_tags, conflict_tags),
    cio_view=None,
    mandate_neutral=True,   # position is kept as-is, mandate weight unchanged
    fit_gain=None,
    sources=[{"type": "keep_reason", "text": reason}],
)
```

New helper `_build_keep_reason(all_candidates, exclusion_tags, conflict_tags) → str` explains:
- "No CIO BUY candidates exist in this sector/industry group" (empty query result)
- "All N CIO BUY candidates in {industry_group} hit the client's {tag} exclusion" (all blocked by E9)
- "All N candidates are below the fit-gain threshold" (blocked by E12 — only when near-conflict case)

Moment escalation (UC-6, §11 E11 "optionally") — deferred. The keep record in `swap_proposals` is
sufficient for E11 at MVP. Moment creation (writing to `moments` table) can be added when TASK-032
(alerts) is wired.

#### 4. GET /clients/{id}/portfolio/swaps — expose keep decisions
The read endpoint currently groups only real proposals. TASK-023 adds `kept_positions` to the response
so the frontend can show positions where no swap was found, with explanation.

New response field (no endpoint URL change):
```python
class KeptPosition(BaseModel):
    position_id: str
    issuer: str | None
    security: str | None
    industry_group: str | None
    sub_asset_class: str | None
    current_chf: float | None
    current_fit_score: float | None
    conflict_tags: list | None
    keep_reason: str | None   # dna_reason from the keep SwapProposal row

class SwapProposalsResponse(BaseModel):
    ...
    positions: list[PositionSwaps]      # existing — actual swap candidates
    kept_positions: list[KeptPosition]  # new — E11 keep decisions
```

The existing GET query already fetches keep records via the `outerjoin(CIORecommendation, ...)` — rows
where `candidate_isin=None` will have `cio=None` but are still returned. Only the response-building
logic needs to branch on `proposal.candidate_isin is None`.

### Existing Resources Found
- **`compute_swaps()`** in `backend/app/loaders/swap.py:31` — extend in place (no new file)
- **`_score_holding()`** in `backend/app/loaders/fit.py:29` — already imported; no change
- **`SwapProposal` ORM model** in `backend/app/models/derived.py:131` — all nullable fields; no migration
- **`SwapProposalsResponse`** in `backend/app/routers/portfolio.py:144` — add `kept_positions` field
- **`GET /clients/{id}/portfolio/swaps`** in `backend/app/routers/portfolio.py:153` — update grouping logic
- **`_build_dna_reason()`** in `backend/app/loaders/swap.py:200` — keep for real proposals; add `_build_keep_reason()` alongside

### Dependencies Required
- Frontend packages: none (backend-only)
- Backend packages: none new
- Database migrations: none — all relevant columns are already nullable
- Docker services: postgres (already running)
- Seeding order unchanged: seed/portfolio → seed/tags → seed/dna → seed/fit → seed/swap

### Impact Assessment

#### Files to Modify
- `backend/app/loaders/swap.py` — set `FIT_GAIN_THRESHOLD = 0.10`; add precedence labels; add `_build_keep_reason()`; write keep record on E11
- `backend/app/routers/portfolio.py` — add `KeptPosition` model; add `kept_positions` to `SwapProposalsResponse`; update GET query grouping to split keep records from proposals

#### Files to Read (no modification)
- `backend/app/loaders/fit.py` — `_score_holding()` import unchanged
- `backend/app/models/derived.py` — `SwapProposal` schema verified nullable; no migration

#### Components Affected
- `swap_proposals` table: **MEDIUM** — same shape, new rows where `candidate_isin=None`
- `GET /clients/{id}/portfolio/swaps`: **MEDIUM** — response model expands with `kept_positions`; backwards-compatible (new field)
- TASK-032 (alerts engine): **LOW** — reads swap proposals; keep records (`candidate_isin=None`) should be filtered out or handled explicitly in the alerts logic

#### API Changes
- `GET /clients/{client_id}/portfolio/swaps` response: adds `kept_positions: list[KeptPosition]` — additive, non-breaking

#### Database Changes
- `swap_proposals`: new rows with `candidate_isin=NULL` for E11 keep decisions; existing query in GET endpoint fetches them via `outerjoin` already

### Implementation Checklist
- [x] Set `FIT_GAIN_THRESHOLD = 0.10` in `swap.py` (change from 0.0)
- [x] Add E9 precedence labels (P1–P5) as comments in the candidate-filtering loop
- [x] Add `_build_keep_reason(all_candidates, exclusion_tags, conflict_tags)` helper in `swap.py`
- [x] On E11 (`not scored`): write `SwapProposal(candidate_isin=None, dna_reason=keep_reason, ...)` instead of just `log.warning`
- [x] Keep the `log.warning("swap.no_compliant_candidate", ...)` call alongside the keep record (observability)
- [x] Add `KeptPosition` Pydantic model to `portfolio.py`
- [x] Add `kept_positions: list[KeptPosition]` to `SwapProposalsResponse`
- [x] In GET /swaps grouping logic: branch on `proposal.candidate_isin is None` → populate `kept_positions`; else → existing `positions` map
- [x] Update GET /swaps log event to include `kept_count`
- [x] Smoke-test: rerun `seed/swap`; check that conflict positions with no candidates now have a `swap_proposals` row with `candidate_isin=NULL`
- [x] Verify GET /swaps returns `kept_positions` list populated with keep records
- [x] Verify `kept_positions` and `positions` are mutually exclusive (no position appears in both)
- [x] Idempotency: run `seed/swap` twice; same proposal + keep record counts

### Risk Analysis
- **Risk Level**: LOW
- **Main Risks**:
  - *`FIT_GAIN_THRESHOLD` change suppresses real proposals*: Only affects candidates where `fit_gain` is
    in `(0.0, 0.10]`. In current dataset all valid candidates gain ≥ 0.5 (exclusion→base score). No
    real proposals suppressed. Mitigation: log count of threshold-suppressed candidates per run.
  - *Keep record written for positions that later get resolved*: Delete-and-reload pattern handles this
    correctly — `delete(SwapProposal).where(holding_id.in_(position_ids))` clears both proposals and
    keep records before reloading. No stale records.
  - *TASK-032 reads `swap_proposals` and may trip on null-candidate rows*: Tag keep records clearly
    via `sources[0].type == "keep_reason"` so future consumers can filter. Document in TASK-032 ticket.

### Estimated Effort
- Original: **S**
- Adjusted: **S** — All changes are in-place edits to two existing files. No new tables, no migrations,
  no new endpoints. The main work is the `_build_keep_reason()` helper + response model update.

---

## Implementation (2026-06-20)

**Files modified**
- `backend/app/loaders/swap.py` — `FIT_GAIN_THRESHOLD` raised `0.0 → 0.10` (E12). E9 precedence
  labels P1–P5 added as inline comments at each filter gate in the candidate query and inner loop.
  `all_candidates = list(candidates)` captured before the filter loop. `_build_keep_reason()` pure
  helper added alongside `_build_dna_reason()` — three branches: no CIO BUY candidates in sector;
  all candidates hit client exclusion (names the tag); all cleared exclusions but below threshold.
  E11 block now calls `_build_keep_reason()`, keeps the `log.warning` (with `keep_reason=` field),
  and writes `SwapProposal(candidate_isin=None, dna_reason=keep_reason, sources=[{"type":"keep_reason",...}])`.
- `backend/app/routers/portfolio.py` — `KeptPosition` Pydantic model added. `SwapProposalsResponse`
  gains `kept_positions: list[KeptPosition]`. `get_portfolio_swaps()` grouping loop branches on
  `proposal.candidate_isin is None`: keep records → `kept_map`; real proposals → `position_map`.
  Log event includes `kept_count`.

**Verified live (POST /admin/seed/swap → GET /clients/{id}/portfolio/swaps):**
- `seed/swap` → `{"clients_processed":7,"proposals_written":20}` (20 keep records, 0 real proposals)
- DB: `SELECT COUNT(*) FILTER (WHERE candidate_isin IS NULL)` → 20 keep records ✓
- Sample keep reason: `"All 2 CIO BUY candidate(s) in Information Technology (Foreign (Dev. Markets)) hit the us-tech exclusion"` ✓
- GET /swaps for Sample Growth client: `conflict_positions=0, total_proposals=0, kept_positions=20` ✓
- `kept_positions` and `positions` mutually exclusive ✓
- Idempotency: second `seed/swap` call → same 20 rows in DB ✓
- No migration required — all `SwapProposal` candidate columns already nullable ✓

**Note — all records are keep decisions:** With the current CIO BUY dataset, E11 fires for every
conflict position because all IT sector BUY candidates carry the `us-tech` tag, which is also the
client's exclusion. Real swap proposals will appear once either (a) the CIO list is updated with
non-us-tech IT alternatives, or (b) real CRM persona DNA is extracted with different exclusion
profiles. The engine logic and E11 explanations are correct per spec.
