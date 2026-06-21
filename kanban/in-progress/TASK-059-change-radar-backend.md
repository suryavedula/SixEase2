# TASK-059: Event-inversion + aggregate impact scoring API

**Status:** IN-PROGRESS · **Epic:** EPIC-08 · **Parent:** TASK-058 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
New endpoint that returns the **top-N changes across the whole book**, each carrying its
impacted-client list. Inverts the existing per-client alerts/news into event-centric records.

- Normalise every signal (news, CIO rec flip, drift_breach, stale_sell, email events from
  TASK-060) into `{action, entity, source, ts, magnitude}`.
- Resolve `entity` → impacted clients by **database-wide exposure**: instrument → all holders;
  sector/industry-group → all tilted clients; client → that client; macro → all by mandate.
- Score each event: `impact = Σ_clients(exposure_chf × magnitude × dna_relevance) × recency`.
- Return ranked events with per-client breakdown (exposure CHF/%, drift caused, DNA note) and a
  suggested action per client + a batch action when one entity hits many.

## Acceptance Criteria
- [ ] `GET /radar` (or `/book/changes`) returns ranked events with impacted-client arrays
- [ ] Exposure aggregates across **all** client portfolios, not one
- [ ] Reuses alert classes (drift_breach, stale_sell) rather than recomputing
- [ ] Every number traceable to a data tool; no figures authored by the model (grounding rule)
- [ ] Unmatched/unresolved entities surfaced explicitly, never silently dropped (no-fallbacks)
- [ ] Tests cover fan-out (1 event → N clients) and scoring/ranking

## Technical Approach
### Reuse
`alerts.py` models + query helpers, `news.py` match results, swap engine (TASK-021) for the
"suggested fix" instrument, portfolio exposure lookups.
### New
Event-normaliser + entity→clients join + aggregate scorer; thread/event dedup so one entity
doesn't appear as multiple rows.

## Dependencies
TASK-021 (swap engine) · TASK-022 (drift) · TASK-028 (news-match) · TASK-032/034 (alert gen/rank)

## Refs
backend/app/routers/alerts.py · backend/app/news.py · docs/Requirements.md §15

---

## Technical Analysis (Auto-generated 2026-06-20)

**Key finding:** the fan-out is *already half-built*. `NewsItem.client_ids` (JSONB, GIN-indexed) and
`Alert.client_id` already link every signal to its clients per-client. This task **inverts and
aggregates** those existing rows by triggering entity — it does **not** build a new fan-out engine,
and it must **reuse** `compute_rank_score` rather than invent a parallel score.

### Existing Resources Found
**Models (exact, with file:line)**
- `Alert` — `models/derived.py:173`. Columns: `client_id`, `alert_class:str|None`, `action_type:ActionType`, `severity:Severity`, `trigger`, `why`, `suggested_action`, `confidence:float|None`, `status:AlertStatus`, `evidence:JSONB`, `rank_score:float|None`, `created_at`. Index `ix_alerts_client_status_severity`.
- alert_class string values (`loaders/alerts.py:41`, `drift.py:33`): `drift_breach · stale_sell · news_impact · good_news · panic · dna_conflict · values_drift · quiet_client · overdue_promise · behavioural_guardrail`.
- Enums (`models/enums.py`): `ActionType{Trade,ReachOut,Acknowledge,Watch}` (l.28), `Severity{Critical,Attention,FYI}` (l.37), `AlertStatus{open,acted,dismissed,snoozed,converted}` (l.45), `CIORating{BUY,HOLD,SELL}` (l.20).
- `NewsItem` — `derived.py:91`. `client_ids:JSONB` (UUID strings, `ix_news_client_ids` GIN), `event_cluster_id:str` (`ix_news_event_cluster` — **the dedup key**), `impact:"threat"|"opportunity"|"moment"`, `sentiment`, `matched_holdings`, `matched_themes`, `published_at`, `is_seeded`, `headline`, `source`, `url`.
- `Position` — `source.py:54`. Exposure join keys: `client_id`, `isin`, `valor`, `mic`, `sub_asset_class`, `industry_group`, `region`, `issuer`, `current_chf:Numeric`, `target_chf`, `quantity`. Indexes `ix_positions_valor/isin/slot(sub_asset_class,industry_group)`.
- `EnrichedHolding` — `derived.py:70`. `position_id` (unique FK), `tags:JSONB{region/sector/value:[...]}`, `fit_score:float` (0.0 = exclusion), `conflicts:JSONB`.
- `Client` — `source.py:22` (`name`, `mandate:Mandate{Defensive,Balanced,Growth}`). `ClientDNA` — `derived.py:43` (`values`, `exclusions`, `tilts`, `temperament`, `promises`, …) → DNA-relevance + emotional multiplier. `ClientWatchlist` — `derived.py:235` (`entities`, `themes`, `keywords`).
- `CIORecommendation` — `source.py:106`. `rating:CIORating`, `rating_since:date`, `industry_group`, `isin`, `sub_asset_class`, `cio_view`, `is_swap_candidate`. **SELL-flip detection** pattern already at `drift.py:179` (held positions ∩ SELL list, severity escalates past 90d).
- `SwapProposal` — `derived.py:137`. `holding_id`, `candidate_isin`, `candidate_valor`, `fit_gain:float`, `dna_reason`, `cio_view`, `mandate_neutral`, `sources:JSONB` (`ix_swap_holding`). → the per-client **suggested fix**.

**Scoring (reuse, do not reinvent)**
- `loaders/alert_rank.py:68` `compute_rank_score(alert, temperament) = SEVERITY_BASE × CLASS_WEIGHT × confidence × emotional_multiplier`. `_SEVERITY_BASE{CRITICAL:3,ATTENTION:2,FYI:1}` (l.27); `_CLASS_WEIGHT` (l.33, dna_conflict:1.0…good_news:0.4); 1.3× emotional multiplier on anxious temperament (l.56). The aggregate event score `Σ_clients(exposure_chf × magnitude × dna_relevance) × recency` should compose **over** these per-client rank_scores, not replace them.

**Router/test conventions**
- `routers/alerts.py:1` — `APIRouter(prefix=..., tags=[...])`, session via `session: AsyncSession = Depends(get_session)` (`main.py:37`), Pydantic response models serialise enums via `.value`. New routers registered in `main.py:113` `app.include_router(...)`.
- Tests (`backend/tests/`): pure-fn style (`test_news.py`) + async `MagicMock`/`AsyncMock` session style (`test_alert_noise.py:109`). `@pytest.mark.asyncio`, mock `session.execute` → `result.all()/scalars()`.

### Dependencies Required
- **No new backend packages.** All models, enums, swap engine, rank scorer, Event Registry client present. Upstream deps (TASK-021 swap, TASK-022 drift, TASK-028 news-match, TASK-032/034 alert gen/rank) are **done and in the codebase**.
- DB: Postgres+pgvector already running; new optional `ChangeEvent` table or a query-time aggregation (decision below).
- Email events (TASK-060) feed in later — design the normaliser to accept that source without coupling to it now.

### Impact Assessment
#### Files to Modify
- `backend/app/main.py` — register new router (`app.include_router`). LOW.
- `backend/app/routers/admin.py` — optional `/admin/seed/radar` if events are materialised. LOW.
#### New Files
- `backend/app/routers/changes.py` (or `radar.py`) — `GET /radar` + per-event detail; Pydantic `RadarEvent`/`ImpactedClient` models.
- `backend/app/loaders/change_radar.py` — event normaliser (`{action, entity, source, ts, magnitude}`), entity→clients resolver, aggregate scorer, dedup.
- `backend/tests/test_change_radar.py` — fan-out (1 event → N clients) + scoring/ranking.
#### Components Affected
- Per-client alert/news pipeline — **read-only reuse**, not modified: LOW regression risk.
#### API Changes
- New `GET /radar` → ranked events, each with `impacted_clients[]` (exposure CHF/%, drift caused, DNA note, suggested action) + optional batch action. Additive.
#### Database Changes
- **Open decision:** materialised `ChangeEvent` table vs. query-time aggregation over `Alert` + `NewsItem`. Lean **query-time first** (the entity is derivable: news→`event_cluster_id`, drift/stale_sell→`Position.isin/industry_group`, CIO flip→`CIORecommendation.isin`), add a table only if latency demands. If materialised, index the triggering-entity key.

### Implementation Checklist
- [ ] Normalise every signal to `{action, entity, source, ts, magnitude}`; entity carries a type (`instrument|sector|client|macro`) driving the resolver.
- [ ] Resolve entity→clients: instrument→`Position.isin/valor` holders; sector→`Position.industry_group`/`EnrichedHolding.tags.sector`; client→self; macro→all weighted by `Client.mandate`.
- [ ] Reuse `compute_rank_score` per client; aggregate `Σ(exposure_chf × magnitude × dna_relevance) × recency` on top — tune weights here (carries TASK-058 open decision).
- [ ] Dedup by `event_cluster_id` (news) / entity key so one entity = one row.
- [ ] Per-client suggested fix from `SwapProposal` (best `fit_gain` for the holding); reuse `stale_sell`/`drift_breach` alerts rather than recomputing (AC).
- [ ] Grounding: every CHF/%/drift number from a data tool; model authors no figures (AC).
- [ ] No-fallbacks: unresolved/unmatched entities returned in an explicit `unresolved[]`, never silently dropped (AC + memory rule).
- [ ] Router: `Depends(get_session)`, enum `.value` serialisation, register in `main.py`; per-client commit if materialising.
- [ ] Tests: fan-out 1→N + scoring/ranking + dedup, following `test_alert_noise.py` async-mock pattern.

### Risk Analysis
- **Risk Level:** MEDIUM.
- **Main Risks:**
  - *Duplicate fan-out engine* — re-implementing what `NewsItem.client_ids`/`Alert.client_id` already give. Mitigation: invert existing rows; the normaliser only adds entity-keying + aggregation.
  - *Scoring mis-ranks at book scale* — naïve `Σ` lets many tiny exposures outweigh one critical breach. Mitigation: compose over proven `compute_rank_score`; validate ordering against persona fixtures; keep weights configurable.
  - *Entity resolution gaps* (e.g. macro events with no instrument key) silently producing empty impact. Mitigation: explicit `unresolved[]` surface (no-fallbacks); test the macro→mandate path.
  - *Dedup misses* across channels (same event as news + email). Mitigation: `event_cluster_id` first, then entity+day key.

### Estimated Effort
- Original: **M**. Adjusted: **M** (unchanged). Inversion + aggregation + scorer reuse + tests is genuine M work, but every primitive (models, swap, rank, news-match) already exists, so no upward revision. Materialising a `ChangeEvent` table would push toward M+/L — defer it.
