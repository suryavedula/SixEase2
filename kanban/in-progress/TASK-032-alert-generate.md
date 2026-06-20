# TASK-032: Alert generation from all signals

**Status:** IN-PROGRESS · **Epic:** EPIC-08 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Generate alerts from news impact, drift, stale SELL, DNA conflict, behavioural guardrail, good-news, quiet-client/overdue-promise, panic, values-drift. Each carries trigger + evidence + why + suggested action + confidence.

## Acceptance Criteria
- [ ] alerts produced from each signal source (AL1)
- [ ] anatomy fields populated (AL3)
- [ ] traceable evidence attached (G2)

## Dependencies
TASK-022 (**DONE** — `loaders/drift.py` fully implemented: `drift_breach` + `stale_sell` alerts written; `POST /admin/seed/drift` live)
TASK-028 (**IN-PROGRESS** — `news_items` table exists (migration 0007 adds `client_ids` JSONB); news-dependent generators degrade gracefully if no rows exist yet)

## Refs
Requirements §15 AL1/AL3

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **`backend/app/routers/alerts.py`** — `GET /clients/{client_id}/alerts` already implemented and
  registered in `main.py`. Supports `?status=` and `?alert_class=` filters. **No changes needed.**
- **`backend/app/louters/drift.py`** — `compute_drift()` writes `drift_breach` + `stale_sell` alerts for
  all clients. Already called by `POST /admin/seed/drift` in `admin.py`. **Fully satisfied by TASK-022.**
- **`Alert` ORM model** (`models/derived.py:173`) — all AL3 anatomy fields present: `client_id`,
  `alert_class` (Text), `action_type` (ActionType enum), `severity` (Severity enum), `trigger`,
  `why`, `suggested_action`, `evidence` (JSONB), `confidence` (Float), `status` (AlertStatus).
  **No migration needed.**
- **`models/enums.py`** — `ActionType.{TRADE,REACH_OUT,ACKNOWLEDGE,WATCH}`, `Severity.{CRITICAL,ATTENTION,FYI}`,
  `AlertStatus.OPEN`. All required enum values present.
- **`models/derived.py:92` `NewsItem`** — `client_ids` (JSONB, migration 0007), `matched_holdings`,
  `matched_themes`, `impact` (threat/opportunity/non-financial moment), `sentiment`, `event_cluster_id`.
  Available for news-driven generators once TASK-028 runs.
- **`models/derived.py:232` `ClientWatchlist`** — present but consumed by TASK-028; TASK-032 does not
  read watchlists directly.
- **`models/derived.py:43` `ClientDNA`** — `promises` (JSONB list), `exclusions` (JSONB), `tilts` (JSONB),
  `temperament` (Text). Source for `overdue_promise` + `behavioural_guardrail` + `panic` calibration.
- **`models/derived.py:70` `EnrichedHolding`** — `fit_score` (Float), `conflicts` (JSONB breakdown of
  exclusion/tilt hits). Source for `dna_conflict` + `values_drift`.
- **`models/derived.py:137` `SwapProposal`** — `dna_reason` (Text), `candidate_isin`. Source for
  `behavioural_guardrail`: if a CIO BUY swap candidate still conflicts with exclusions.
- **`models/source.py:34` `Interaction`** — `date` (Date), `note` (Text). Source for `quiet_client`.
- **`models/source.py:105` `CIORecommendation`** — `tags` (JSONB, from migration 0003), `rating`,
  `industry_group`. Source for `behavioural_guardrail` cross-check.
- **`loaders/drift.py`** — canonical idempotency pattern: `DELETE WHERE client_id AND alert_class IN (...)`,
  then insert fresh, then `await session.commit()` per client. **Reuse exactly.**
- **`app/logging.py`** — `get_logger(__name__)` + `log.info(key, **kwargs)`.
- **`app/db.py`** — `get_session` FastAPI dep; `AsyncSession` for loaders.
- **`admin.py`** — established `POST /admin/seed/...` pattern with `RuntimeError → 409`,
  generic exception → 500.

### Dependencies Required
- **Frontend packages:** none (backend-only compute)
- **Backend packages:** none new — `sqlalchemy[asyncio]`, `asyncpg`, `datetime` already present
- **Database migrations:** none — `alerts` table exists since migration 0001; all PG enum types exist
- **Docker services:** postgres (running); no Ollama calls needed for TASK-032 generators
- **Seeding order:**
  - `seed/portfolio` → `seed/tags` → `seed/dna` → `seed/fit` → **`seed/alerts`** (for DNA-derived signals)
  - `seed/drift` can run in parallel (its output is not consumed by TASK-032)
  - `scan/news` (TASK-028) → `seed/alerts` (for news signals) — news alerts degrade gracefully to 0 if no news rows

### Impact Assessment

#### Files to Create
- `backend/app/loaders/alerts.py` — `generate_alerts(session)` orchestrator + 7 private signal generators

#### Files to Modify
- `backend/app/routers/admin.py` — add `POST /admin/seed/alerts` + update module docstring with TASK-032
  (additive only; existing endpoints unchanged)

#### Files Already Complete (no changes)
- `backend/app/routers/alerts.py` — read endpoint already implemented
- `backend/app/main.py` — alerts router already registered
- `backend/app/loaders/drift.py` — drift_breach + stale_sell already implemented (TASK-022)
- `backend/app/models/derived.py` — Alert model already has all required fields

#### Components Affected
- `alerts` table: **HIGH** — new rows written for 7 signal classes per client
- `enriched_holdings` / `positions`: **LOW** — read-only
- `interactions`: **LOW** — read-only (last-date query only)
- `client_dna.promises`: **LOW** — read-only
- `news_items`: **LOW** — read-only (degrades gracefully if empty)
- `admin.py`: **LOW** — additive only
- TASK-033 (noise control) / TASK-034 (ranking): **HIGH dependency downstream** — consume alerts table

#### API Changes
- **New:** `POST /admin/seed/alerts` → `{"status":"ok","loaded":{"clients_processed":N,"news_impact":N,"dna_conflict":N,"behavioural_guardrail":N,"good_news":N,"quiet_client":N,"overdue_promise":N,"panic":N,"values_drift":N}}`

#### Database Changes
- No schema change. New rows written to `alerts` table only.

---

### Signal Design (`backend/app/loaders/alerts.py`)

All generators share the same idempotency contract as `drift.py`:
DELETE existing alerts for `alert_class IN (managed_classes)` per client, then insert fresh, then commit.
`drift_breach` and `stale_sell` are NOT in the delete scope — they're owned by `drift.py`.

#### Managed alert classes
```python
_MANAGED_CLASSES = [
    "news_impact", "good_news", "panic",
    "dna_conflict", "values_drift",
    "quiet_client", "overdue_promise",
    "behavioural_guardrail",
]
```

#### 1. `_generate_news_alerts(session, client, news_items) → int`
Source: `news_items` rows where `client.id` appears in `news_item.client_ids`.
```
impact = "threat"  OR impact = "non-financial moment"
  → alert_class = "news_impact", action_type = REACH_OUT (or TRADE if own-axis), severity = ATTENTION
impact = "opportunity" (care-axis match, i.e. matched_themes is non-empty)
  → alert_class = "good_news", action_type = REACH_OUT, severity = FYI
sentiment ≤ -0.5 AND matched_holdings is non-empty (own-axis)
  → alert_class = "panic", action_type = REACH_OUT, severity = ATTENTION/CRITICAL
```
Dedup on `event_cluster_id`: one alert per cluster per client.
If no news_items rows for client → return 0 (graceful degradation).

#### 2. `_generate_dna_conflict_alerts(session, client) → int`
Source: JOIN `Position` × `EnrichedHolding` WHERE `enriched_holdings.fit_score = 0.0`
(fit_score=0 means at least one exclusion tag triggered).
```
For each position with fit_score=0:
  alert_class = "dna_conflict"
  action_type = TRADE
  severity = CRITICAL
  trigger = f"{position.issuer or position.isin} conflicts with stated exclusion"
  why = "This holding contradicts a stated red line extracted from your client notes"
  suggested_action = "Review for swap to a compatible same-sector replacement (see swap proposals)"
  evidence = [{"isin": ..., "issuer": ..., "current_chf": ..., "conflicts": enriched.conflicts}]
  confidence = 1.0
```
Requires `seed/fit` to have run first. If no `enriched_holdings` rows → return 0 (skip gracefully).

#### 3. `_generate_values_drift_alert(session, client) → int`
Source: aggregate of `enriched_holdings.fit_score` for all client positions.
```
mean_fit = mean(enriched.fit_score for all non-null holdings)
n_below = count where fit_score < 1.0 (no tilt bonus)
If mean_fit < 0.65 AND n_below >= 3:
  alert_class = "values_drift"
  action_type = ACKNOWLEDGE
  severity = FYI
  trigger = f"Portfolio mean fit score {mean_fit:.2f} — values alignment below target"
  why = "The current portfolio composition does not reflect the client's expressed values and tilts"
  suggested_action = "Review holding mix against client DNA to identify alignment opportunities"
  evidence = [{"mean_fit_score": mean_fit, "positions_below_baseline": n_below, "total_positions": n_total}]
  confidence = 0.8
```
At most 1 `values_drift` alert per client.

#### 4. `_generate_quiet_client_alert(session, client) → int`
Source: `max(Interaction.date)` WHERE `Interaction.client_id = client.id`.
```
QUIET_DAYS = 60
last_contact = await session.scalar(select(func.max(Interaction.date)).where(...))
if last_contact is None:
  days_since = None; severity = ATTENTION
else:
  days_since = (date.today() - last_contact).days
  if days_since < QUIET_DAYS: return 0
  severity = CRITICAL if days_since > 120 else ATTENTION
alert_class = "quiet_client"
action_type = REACH_OUT
trigger = f"Last meaningful contact {days_since}d ago" if days_since else "No recorded contact"
why = "Client has not been contacted recently — relationship health at risk"
suggested_action = "Proactively reach out; review open promises before contact"
evidence = [{"last_contact_date": str(last_contact), "days_since": days_since}]
confidence = 1.0
```

#### 5. `_generate_promise_alerts(session, client, dna) → int`
Source: `ClientDNA.promises` JSONB list (items: `{value, source, confidence}`).
```
For each promise in (dna.promises or []):
  alert_class = "overdue_promise"
  action_type = REACH_OUT
  severity = ATTENTION
  trigger = f"Open promise: {promise.get('value', '')}"
  why = "An outstanding commitment was extracted from CRM notes — follow-up required"
  suggested_action = "Review the promise and either fulfil it or update the client"
  evidence = [{"promise": promise.get("value"), "source_note": promise.get("source"), "confidence": promise.get("confidence")}]
  confidence = promise.get("confidence", 0.7)
```

#### 6. `_generate_guardrail_alerts(session, client, dna) → int`
Source: `SwapProposal` rows for client's positions where `dna_reason` is not None
(meaning the swap was DNA-conflict-driven), cross-checked against `CIORecommendation.tags`
to find BUY candidates that themselves conflict with the client's exclusions.
```
exclusion_tags = frozenset(item["tag"] for item in (dna.exclusions or []) if item.get("tag"))
For each swap_proposal for client's positions:
  If candidate has tags AND tags["value_tags"] ∩ exclusion_tags ≠ ∅:
    alert_class = "behavioural_guardrail"
    action_type = ACKNOWLEDGE
    severity = ATTENTION
    trigger = f"Proposed replacement {candidate_isin} may conflict with stated red lines"
    why = "A CIO-suggested swap candidate shares tags with the client's stated exclusions"
    suggested_action = "Verify candidate alignment with client DNA before proposing"
    evidence = [{"candidate_isin": ..., "conflicting_tags": [...], "exclusions": [...]}]
    confidence = 0.9
If no swap proposals for client → return 0
```

### Public API
```python
async def generate_alerts(session: AsyncSession, client_id: uuid.UUID | None = None) -> dict[str, int]:
    """Generate all non-drift alert classes for all clients (or one).

    Idempotent: deletes managed classes per client before re-inserting.
    drift_breach and stale_sell are owned by loaders/drift.py — not touched here.
    """
```

### Implementation Checklist
- [ ] Create `backend/app/loaders/alerts.py` with `generate_alerts(session, client_id=None)`
- [ ] Implement `_generate_news_alerts`: dedup on event_cluster_id; graceful if news_items empty
- [ ] Implement `_generate_dna_conflict_alerts`: JOIN positions × enriched_holdings WHERE fit_score=0
- [ ] Implement `_generate_values_drift_alert`: aggregate mean fit_score; 1 alert per client max
- [ ] Implement `_generate_quiet_client_alert`: func.max(Interaction.date); 60d threshold
- [ ] Implement `_generate_promise_alerts`: iterate ClientDNA.promises; 1 alert per promise
- [ ] Implement `_generate_guardrail_alerts`: swap_proposals × CIORecommendation tags × exclusions
- [ ] Idempotency: DELETE WHERE alert_class IN (_MANAGED_CLASSES) per client before re-insert
- [ ] Per-client commit (partial failure safety — same pattern as drift.py)
- [ ] `log.info("alerts.client_processed", client=..., **counts_per_class)`
- [ ] `log.info("alerts.generate_complete", clients=..., **totals)`
- [ ] Add `POST /admin/seed/alerts` to `backend/app/routers/admin.py`
- [ ] Update `admin.py` module docstring to list TASK-032 endpoint
- [ ] Import `generate_alerts` in `admin.py`
- [ ] Smoke-test: `POST /admin/seed/alerts`, then `GET /clients/{id}/alerts` — expect all 7 classes
- [ ] Idempotency test: call twice, assert same row counts
- [ ] Follow CLAUDE.md: NEVER duplicate drift.py logic; NEVER add a second Alert model or read router

### Risk Analysis
- **Risk Level:** MEDIUM
- **Main Risks:**
  - *TASK-028 not complete:* News-derived generators (news_impact, good_news, panic) find 0 rows.
    **Mitigation:** graceful degradation — empty `news_items` table → these generators return 0, no error.
  - *`seed/fit` not run:* `enriched_holdings` has no fit_score → `dna_conflict` + `values_drift` return 0.
    **Mitigation:** check for missing `EnrichedHolding` rows per client and skip with a `log.warning`.
  - *`ClientDNA.promises` structure variance:* promises items may have different shapes across personas.
    **Mitigation:** use `.get()` with fallbacks on all promise dict accesses.
  - *Guardrail CIORecommendation.tags may be None:* if `seed/tags` wasn't run for CIO rows.
    **Mitigation:** guard `if cio_row.tags and cio_row.tags.get("value_tags")`.
  - *Alert dedup on re-seed:* if `drift_breach` alerts exist and we accidentally delete them.
    **Mitigation:** `_MANAGED_CLASSES` explicitly excludes `drift_breach` and `stale_sell`.

### Estimated Effort
- Original: **M**
- Adjusted: **M** — 7 signal generators + 1 admin endpoint. Pattern is fully established (drift.py).
  News generators require no new infrastructure. Main complexity is the guardrail cross-check and
  the news-alert dedup. No new schema, no LLM calls, no new dependencies.
