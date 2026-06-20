# TASK-022: Drift and stale-SELL detection

**Status:** IN-PROGRESS · **Epic:** EPIC-05 · **Priority:** P0 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Compute sub-asset-class drift vs target and flag breaches beyond plus/minus 2.0pp; flag SELL-rated held positions with age since rating.

## Acceptance Criteria
- [ ] drift breaches detected per mandate
- [ ] stale SELL flagged with age
- [ ] outputs feed alert engine

## Dependencies
TASK-008

## Refs
Requirements §11 E10, §10.3

---

## Technical Analysis (Auto-generated 2026-06-20)

### Dependency Status
- **TASK-008** (load portfolios) — in `in-progress/`, fully implemented and verified live.
  `positions.current_chf` + `positions.target_chf` are populated for all 3 seed clients
  (207 positions). `mandate_strategies.target_weight` is loaded for 39 rows (13 sub-asset-
  classes × 3 mandates). `cio_recommendations` has 4 SELL rows with `rating_since` populated.
  The dependency is fully satisfied — proceeding.

### Existing Resources Found
- **`backend/app/models/derived.py`** — `Alert` ORM model with all needed fields:
  `client_id`, `alert_class` (Text), `action_type` (ActionType enum), `severity` (Severity
  enum), `trigger` (Text), `why` (Text), `suggested_action` (Text), `evidence` (JSONB),
  `status` (AlertStatus, default OPEN). **No new model or migration needed.**
- **`backend/app/models/enums.py`** — `ActionType.TRADE`, `Severity.CRITICAL/ATTENTION`,
  `AlertStatus.OPEN`, `CIORating.SELL`. All required enum values present.
- **`backend/app/models/source.py`** — `Position` (has `sub_asset_class`, `current_chf`,
  `isin`, `client_id`), `Client` (has `mandate`), `MandateStrategy` (has `mandate`,
  `sub_asset_class`, `target_weight`), `CIORecommendation` (has `rating`, `rating_since`,
  `isin`, `cio_view`). All joins available.
- **`backend/app/loaders/swap.py`** — same loader pattern; reuse import structure and
  async session flow.
- **`backend/app/routers/admin.py`** — established `POST /admin/seed/...` pattern; add
  `POST /admin/seed/drift` here following the existing template.
- **`backend/app/routers/portfolio.py`** — pattern for `GET /clients/{client_id}/...`
  endpoints to follow for the alert read endpoint.
- **`backend/app/logging.py`** — `get_logger(__name__)` + `log.info(key, **kwargs)`.
- **`backend/app/db.py`** — `get_session` (FastAPI dep) and `AsyncSession` for loaders.

### Dependencies Required
- **Frontend packages:** none (backend-only compute).
- **Backend packages:** none to add — SQLAlchemy, asyncpg, and datetime are already present.
- **Database migrations:** none — the `alerts` table and all PG enum types exist in `0001`.
- **Docker services:** postgres (already running).

### Impact Assessment

#### Files to Create
- `backend/app/loaders/drift.py` — async `compute_drift(session)` with two sub-functions:
  `_detect_drift_breaches` and `_detect_stale_sells`.
- `backend/app/routers/alerts.py` — `GET /clients/{client_id}/alerts` read endpoint (filter
  by status and alert_class; JSON list for the frontend alert queue).

#### Files to Modify
- `backend/app/routers/admin.py` — add `POST /admin/seed/drift` endpoint + import.
- `backend/app/main.py` — register `alerts` router.

#### Components Affected
- `alerts` table: **HIGH (new data)** — first write; drift_breach + stale_sell rows per client.
- `positions` / `mandate_strategies` / `cio_recommendations`: **LOW** — read-only.
- TASK-032 (alert queue UI): **HIGH dependency downstream** — reads from the alerts table
  this task writes.

#### API Changes
- New: `POST /admin/seed/drift` → `{"status":"ok","loaded":{"clients":N,"drift_breach":N,"stale_sell":N}}`.
- New: `GET /clients/{client_id}/alerts?status=open` → list of alert rows for the frontend.

#### Database Changes
- None (schema migration not needed). First writes to the `alerts` table.

### Drift Computation Design

#### `_detect_drift_breaches(session, client) -> int`

For each client:
1. Fetch all positions with non-null `current_chf` via `select(Position).where(client_id=...)`.
2. `total_chf = sum(p.current_chf for p in positions)`. Skip client if total is 0.
3. Group by `sub_asset_class`: `sac_chf = defaultdict(float)`.
4. Fetch `mandate_strategies` for `client.mandate` → dict `{sac: target_weight}`.
5. For each strategy row, compute:
   - `current_pp = (sac_chf.get(sac, 0.0) / total_chf) * 100`
   - `drift_pp = current_pp - target_weight`  ← target_weight stored as percent (e.g. 15.0)
   - If `abs(drift_pp) > DRIFT_THRESHOLD_PP` (2.0): emit Alert.
6. Alert fields:
   - `alert_class = "drift_breach"`
   - `action_type = ActionType.TRADE`
   - `severity = Severity.CRITICAL if abs(drift_pp) > 5.0 else Severity.ATTENTION`
   - `trigger = f"{sac}: {drift_pp:+.2f}pp (current {current_pp:.2f}%, target {target_weight:.2f}%)"`
   - `why = "Sub-asset-class weight outside the ±2.0pp mandate band (E10)"`
   - `suggested_action = "Rebalance sub-asset class to restore mandate weights"`
   - `evidence = [{"sub_asset_class": sac, "drift_pp": drift_pp, "current_pp": current_pp, "target_pp": target_weight, "total_chf": total_chf}]`

> **Note on target_weight scale:** the "Def %" column in the workbook is an Excel percentage
> cell. If the loader stored the raw underlying float (e.g. `0.15` for 15%), multiply by 100
> before computing drift_pp. Verify with `SELECT target_weight FROM mandate_strategies LIMIT 5`
> — values near 0–1 are decimals; values near 0–100 are already percentage points. The loader
> stores `float(raw)` directly; verify actual stored values before shipping.

#### `_detect_stale_sells(session, client) -> int`

1. Fetch all SELL-rated CIO rows: `select(CIORecommendation).where(rating=CIORating.SELL)`.
2. Build dict `sell_by_isin = {row.isin: row for row in sell_rows}`.
3. Fetch client positions. For each position whose `isin` is in `sell_by_isin`:
   - `cio_row = sell_by_isin[position.isin]`
   - `age_days = (today - cio_row.rating_since).days` (rating_since is a DATE)
   - Alert fields:
     - `alert_class = "stale_sell"`
     - `action_type = ActionType.TRADE`
     - `severity = Severity.CRITICAL if age_days > 90 else Severity.ATTENTION`
     - `trigger = f"{position.issuer or position.isin} — CIO SELL since {cio_row.rating_since} ({age_days}d)"`
     - `why = "Holding a CIO-rated SELL instrument; position should be reviewed for disposal"`
     - `suggested_action = "Review for disposal or swap to a BUY-rated same-sector replacement"`
     - `evidence = [{"isin": position.isin, "issuer": position.issuer, "rating_since": str(cio_row.rating_since), "age_days": age_days, "cio_view": cio_row.cio_view}]`

#### Idempotency
Delete `WHERE client_id = ? AND alert_class IN ('drift_breach', 'stale_sell')` before
re-inserting. This preserves manually created or news-driven alerts for the same client.

### Implementation Checklist
- [ ] Create `backend/app/loaders/drift.py` with `compute_drift(session) -> dict`
- [ ] Implement `_detect_drift_breaches`: SAC aggregation, target lookup, ±2.0pp gate
- [ ] Implement `_detect_stale_sells`: held-ISIN × SELL-list join, age computation
- [ ] Verify `target_weight` scale in DB before computing drift (`SELECT` first or add a guard)
- [ ] Idempotency: DELETE drift_breach/stale_sell alerts per client before re-insert
- [ ] Add `POST /admin/seed/drift` to `backend/app/routers/admin.py`
- [ ] Create `backend/app/routers/alerts.py` with `GET /clients/{client_id}/alerts`
- [ ] Register alerts router in `backend/app/main.py`
- [ ] Smoke-test: call seed/drift, verify alert rows in psql (expect breaches in Balanced + Growth)
- [ ] Idempotency test: call twice, assert same alert counts
- [ ] Follow SOLID principles; reuse `get_logger`, `get_session`, ORM models — no duplicate logic

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - *`target_weight` scale ambiguity* — if stored as decimal (0.15) not percent (15.0), the
    drift computation will be off by ×100. Mitigation: `SELECT target_weight FROM
    mandate_strategies LIMIT 3` and branch on value magnitude, OR add a `target_weight_pp`
    property. Resolve before writing any comparison logic.
  - *`rating_since` is None for some SELL rows* — the workbook had 4 SELL rows; if any lack
    `rating_since`, the age computation would throw. Mitigation: guard `if cio_row.rating_since`
    and set `age_days = None`; still emit the alert without age.
  - *No clients with positions yet (pre-seed state)* — `compute_drift` must gracefully return 0
    alerts rather than erroring if called before seed/portfolio. Mitigation: early-return if
    no clients/positions found.

### Estimated Effort
- Original: **S**
- Adjusted: **S** — pure read-aggregate-write pipeline; no new schema; two well-bounded
  sub-functions + one admin endpoint + one read endpoint. Main complexity is the SAC
  aggregation and the target_weight scale verification.
