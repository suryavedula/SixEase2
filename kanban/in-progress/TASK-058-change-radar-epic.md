# TASK-058: Book-wide Change Radar widget [PARENT]

**Status:** IN-PROGRESS · **Epic:** EPIC-08 · **Priority:** P0 · **Type:** feature · **Effort:** L · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
A single widget that, every time it opens, shows the **top changes across the entire book**
ranked by aggregate impact, each expandable to the **list of impacted clients**, **how it
hits each of them**, and **a one-click fix**. The unit is the *change/event*, not the client.

Core model: every change — whatever its channel — reduces to `{action, entity}`, fans out to
impacted clients by database-wide exposure, is scored, ranked, and rendered.

| Event references… | Impacted clients | Examples |
|---|---|---|
| an instrument / sector | everyone exposed (fan-out by holdings) | news on a held name · CIO SELL flip · **internal email "trim defense names"** |
| a specific client | that one client | inbound client email · CRM life-event note |
| whole book / macro | all, weighted by mandate | rate-hike news · internal "de-risk growth mandates" email |

The channel only decides *how we parse* an event, not how it flows. This is the **event-centric
inversion** of the existing per-client alerts: same signals, grouped by the triggering entity.

## Business value
- The RM's daily "what happened while I wasn't looking, who does it hit, what do I do" surface.
- Personalisation-at-scale: one event hitting N clients → one review, batch-applied per client.
- Human-in-the-loop: every row ends in an RM action; nothing reaches a client automatically.

## Sub-tasks
- [ ] TASK-059: Event-inversion + aggregate impact scoring API (backend)
- [ ] TASK-060: Email ingestion via Microsoft Graph + entity extraction (new source)
- [ ] TASK-061: ChangeRadar widget — top-10, impacted-client expand, batch fix (frontend)

## Completion criteria
All three sub-tasks complete; widget renders live top-10 across the book with at least news +
internal alerts (email source via TASK-060), expands to impacted clients, supports batch + per-client action.

## Existing resources to reuse
`alerts.py` (drift_breach/stale_sell, needs-attention, convert_alert_to_task) · `news.py`
(Event Registry + sentiment) · swap engine (TASK-021) · `EmailDraft` · registry.ts ·
`WidgetContainer` · `CanvasActions`.

## Open decisions (carry into sub-tasks)
- Impact scoring weights: `Σ(exposure × magnitude × dna_relevance) × recency` — tune in TASK-059.
- Azure AD is used **only as email transport** (Graph `Mail.Read`); not an infra dependency.
  Note this exception in docs/Requirements.md so it doesn't read as a contradiction of "no Azure".
- Widget name is a working title ("ChangeRadar" / "Pulse") — finalise before demo.

## Refs
docs/Requirements.md · EPIC-08 (alerts) · EPIC-07 (news-loop) · EPIC-09 (message) · Project-Overview.html

---

## Technical Analysis (Auto-generated 2026-06-20)

The event→client fan-out pipeline this epic needs **already exists end-to-end for the news channel** —
`build_inverted_index` → `run_fanout` → `generate_alerts` → `rank_alerts`. The epic is largely an
*inversion and aggregation layer* over those primitives, plus one genuinely new source (email, TASK-060).

### Existing Resources Found
**Backend**
- `loaders/news_fanout.py` — `build_inverted_index(session) → {keyword: [(client_id, watchlist)]}`,
  `run_fanout(session)` (dequeue one article, fan to matching clients). **The core fan-out engine to invert.**
- `loaders/news_match.py` — `_match_article(article, watchlist) → (matched_holdings, matched_themes)`;
  `_build_impact_messages(...)` + `_ImpactResult(impact: threat|opportunity|moment, reason, confidence)`. Reusable per-event impact classification.
- `loaders/alerts.py` — `generate_alerts(session, client_id=None)` (8 classes incl. `news_impact`, `dna_conflict`); `loaders/drift.py` `compute_drift` (drift_breach/stale_sell).
- `loaders/alert_rank.py` — `rank_alerts(session) → rank_score` (severity × confidence × recency × dedup). **The per-event aggregate score reuses this composite.**
- `loaders/swap.py` — `compute_swaps(session, client_id?)` → `SwapProposal{candidate_isin, fit_gain, dna_reason, cio_view}`. Powers the **one-click fix** per impacted client.
- `news.py` — `search_articles`, `get_recent_activity(newest_uri)`, sentiment in `[-1,1]`.
- `routers/alerts.py` — `transition_alert`, `convert_alert_to_task` (alert→Task, MANUAL mode). Reuse for "RM action" terminal step.
- `routers/orchestrate.py` — `/orchestrate` render protocol (`OrchestrateResponse.specs[]`); admin.py has `/admin/fanout/news` to mirror for changes.
- Data access — `models/source.py` (Client, Position{industry_group,isin,valor,mic,current_chf}, ClientWatchlist), `models/derived.py` (Alert, NewsItem, EnrichedHolding{tags,fit_score}). Find exposed clients via `Position` join on isin/issuer/industry_group.
- `loaders/persona_portfolio.py` — `link_persona_portfolios` (persona→mandate→sample positions) for the seeder (TASK-064).

**Frontend**
- `registry/registry.ts` + `widgets/index.ts` — one-line registration; `WidgetRenderer` auto-renders `{component, props}`.
- `widgets/WidgetContainer.tsx` — `{title, source, badges, children}` panel chrome.
- `shell/CanvasActions.tsx` — `useCanvasActions().addSpecs(specs)` → drill-down (expand impacted clients = append `ClientBook`).
- `widgets/ClientBook.tsx` — filterable `{mandate, hasConflicts, minFit, sortBy}` — **the impacted-client expand list**.
- `widgets/EmailDraft.tsx` + `api/messages.ts` — proven human-in-the-loop approval state machine (`busy: saving|approving|sending`, approved badge, no auto-send). Pattern for **batch fix confirmation**.
- `api/client.ts` (`apiGet/apiPost/apiPatch` + AbortController) & `api/alerts.ts` (`AlertItem` shape) — template for new `api/changes.ts`.
- `shell/AppShell.tsx` / `InputDock.tsx` — `specs[]` state + slash-command/orchestrator mount path (`/changes` or NL → ChangeRadar spec).

### Dependencies Required
- **No new backend packages** — all primitives present (SQLAlchemy models, Event Registry client, LLM provider abstraction).
- **TASK-060 only:** Microsoft Graph (`Mail.Read`) email transport + entity extraction — the one new external dependency. **Azure AD used solely as mail transport, not infra** (note in Requirements.md per open decision).
- **No new frontend packages** — registry + container + canvas-actions cover the widget.
- Docker services unchanged (Postgres+pgvector, Redis already up).

### Impact Assessment
#### Files to Modify
- `frontend/src/registry/registry.ts` + `widgets/index.ts` — register `ChangeRadar` (LOW).
- `backend/app/routers/orchestrate.py` / `admin.py` — add change-radar endpoint + orchestrator widget option (MEDIUM).
- `docs/Requirements.md` — record the Azure-as-transport exception + widget final name (LOW).

#### New Files (per sub-task)
- TASK-059: `loaders/change_radar.py` (event inversion + aggregate impact scoring) + `routers/changes.py`.
- TASK-060: `loaders/email_ingest.py` (Graph) + entity extraction.
- TASK-061: `frontend/src/components/widgets/ChangeRadar.tsx` + `api/changes.ts`.

#### Components Affected
- Per-client alerts pipeline — REUSED, not modified (event view is an aggregation over the same `Alert` rows): LOW risk of regression.
- Orchestrator render set — additive: LOW.

#### API Changes
- New: `GET /changes` (book-wide top-N), `GET /changes/{id}/impacted` (client fan-out), `PATCH /changes/{id}` (status), batch-fix endpoint. Additive, no contract breakage.

#### Database Changes
- Likely a `ChangeEvent` table (or a view over `Alert` grouped by triggering entity) — decide in TASK-059. Email source adds rows to existing `NewsItem`-like ingestion, or a sibling table. Index on triggering-entity key for fan-out.

### Implementation Checklist
- [ ] Invert `news_fanout` (client→events) into entity→clients aggregation rather than building a new engine.
- [ ] Reuse `rank_alerts` composite for the aggregate `Σ(exposure × magnitude × dna_relevance) × recency` score (extend, don't replace).
- [ ] Reuse `swap.compute_swaps` `SwapProposal` for the one-click fix; never author trade figures in the LLM.
- [ ] Reuse `ClientBook` for impacted-client expand (filtered `addSpecs`), `EmailDraft` approval pattern for batch fix.
- [ ] Every row terminates in an RM action (`convert_alert_to_task`); nothing reaches a client automatically.
- [ ] Full traceability — each event cites its CRM note / news URI / CIO source / email.
- [ ] Loading + error states on the widget (mirror `Client360` status machine).

### Risk Analysis
- **Risk Level:** MEDIUM (epic-level; individual sub-tasks lower).
- **Main Risks:**
  - *Email ingestion (TASK-060) is the only true unknown* — Graph auth + entity extraction quality. Mitigation: ship news + internal-alert sources first (already working); gate email behind its own sub-task so the widget demos without it.
  - *Scoring weight tuning* (`exposure × magnitude × dna_relevance × recency`) may mis-rank. Mitigation: start from the proven `rank_alerts` composite, tune in TASK-059 against persona data.
  - *Duplicate engine drift* — risk of re-implementing fan-out instead of inverting it. Mitigation: explicitly build on `build_inverted_index`/`run_fanout`.

### Estimated Effort
- Original: **L**.
- Adjusted: **L** (unchanged). Backend inversion + scoring is M because primitives exist; frontend widget is S (registry + reused ClientBook/EmailDraft); email source (TASK-060) carries the only new-integration weight.
- Reason: high reuse of the existing news fan-out + alert-rank + swap pipeline keeps this from being XL.
