# TASK-064: Simulated-client seeder + house-model baseline

**Status:** IN-PROGRESS · **Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20
**Epic:** EPIC-10 · **Parent:** TASK-062 · **Priority:** P1 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20

## Description
Not an onboarding UI — a way to **simulate adding a client that already has notes + a strategy**,
run the existing DNA-extraction + swap pipeline on it, and produce the data the before/after view
needs. The cleanest demo of the thesis: no drifted holdings, so the contrast is pure.

- Seed a new client from `{notes, mandate}` (reuse the persona-link path in
  `persona_portfolio.py`); run DNA extraction so `ClientDNA` (exclusions/tilts/sources) populates.
- Build the **house/model baseline portfolio** for that mandate: CIO target sub-asset-class weights
  filled with the *default/model* instrument per slot — this is the "before".
- Run the swap engine to produce the **personalised fill** (best-fit CIO-BUY per slot) — the "after".
- Expose both via the portfolio endpoints (or a `?baseline=model` variant) so TASK-065 can render
  model-vs-personalised exactly like existing-client current-vs-swapped.

## Acceptance Criteria
- [x] Can seed a simulated client from notes + mandate; DNA extracts with source citations
- [x] House-model baseline portfolio generated from CIO target weights (the "before")
- [x] Personalised fill generated via swap engine, mandate-neutral, CIO-BUY only (the "after")
- [x] Both portfolios retrievable through portfolio endpoints for the before/after widget
- [x] Identical sub-asset-class weights between model and personalised (mandate-neutral proof)
- [x] No fabricated holdings/prices; everything from data tools (grounding · no-fallbacks)
- [x] Tests: seed→DNA→baseline→personalised pipeline; weight-neutrality assertion

## Implementation (2026-06-20)
**New:** `backend/app/loaders/simulate_client.py` — `seed_simulated_client(session)` seeds one
canned demo client `[SIMULATED] Clara Bauer` (Balanced; 3 notes expressing a fossil-fuel red line
+ sustainability tilt), copies the mandate's Sample book pinned to CIO target weights (zero-drift
house-model "before"), then runs `extract_dna` (Phoeniqs, with citations) → `compute_fit` →
`compute_swaps` scoped to the client (personalised "after"). Pure `find_weight_neutrality_violations`
helper + `_assert_weight_neutral` re-check every proposal keeps its `(sub_asset_class, industry_group)`
slot and raise on any drift.
**New route:** `POST /admin/seed/simulate-client` in `routers/admin.py` (the button; RuntimeError→409).
**Reused/DRY:** added `copy_sample_positions(session, client, mandate, at_target_weight=…)` to
`persona_portfolio.py` (single home for the position-copy logic; persona linking unchanged at the
default `False`). No portfolio/dna endpoint changes, no migration.
**New tests:** `backend/tests/test_simulate_client.py` (10 tests: canned-data integrity + weight-
neutrality assertion) — all pass; full suite 152 passed (pre-existing `langgraph` collection error
in `test_domain_agents.py` is unrelated).

**Live verification (Phoeniqs, running stack):** `POST /admin/seed/portfolio` → `POST
/admin/seed/simulate-client` → `{positions:66, dna:1, fit:66/66, swap:3 proposals}`. DNA: fossil-fuel
exclusion (2 citations) + sustainability tilt (1). Energy fossil holding swaps to a CIO-BUY
alternative (fit_gain 0.5). Allocation: **0/12 drift breaches, max |drift| 0.0** (pure baseline).
Idempotent on re-run.

## Technical Approach
### Reuse
`persona_portfolio.py` (link/copy holdings), DNA extraction loaders, `fit.py`, `swap.py`,
Portfolio Strategies / CIO target weights, Sample Portfolio defaults.
### New
Seeder entry (script or admin route), model-baseline builder (target weights × default instrument),
and a "personalised fill" path that fills empty slots rather than swapping existing ones.

## Dependencies
TASK-021 (swap engine) · DNA extraction (UC-1) · persona_portfolio loader

## Refs
backend/app/loaders/persona_portfolio.py · backend/app/loaders/{fit,swap,tags}.py ·
docs/Requirements.md §UC-27, E5–E8 · data/SwissHacks Portfolio Construction.xlsx (Portfolio Strategies)

## Technical Analysis (Auto-generated 2026-06-20)

### Key realisation — the engine already produces "before/after"
The **house-model baseline for a mandate IS the Sample Portfolio holdings** (CIO model default
instrument per slot, no drift — exactly what the task wants as the clean "before"). A simulated
client is therefore just a *normal client* seeded the same way `link_persona_portfolios()` builds
personas: copy the mandate's Sample positions, extract DNA from notes, then run fit→swap. Once
seeded, the existing portfolio endpoints already expose both sides:
- **"before" (model)** = the seeded Sample positions → `GET /clients/{id}/portfolio/fit` holdings.
- **"after" (personalised)** = best swap candidate per conflict slot → `GET /clients/{id}/portfolio/swaps`.

So the task's "new personalised-fill path that fills empty slots rather than swapping existing ones"
is satisfied by the **existing `compute_swaps()`** applied to the model baseline — swapping the
default instrument for a same-`(sub_asset_class, industry_group)` CIO-BUY best-fit is functionally
identical to "filling the slot with the best-fit instrument." **No new fill engine is needed**; this
is a deliberate simplification (avoid duplicating `swap.py`). The only genuinely new code is the
**seeder** that creates the client + interactions and runs the per-client pipeline.

### Existing Resources Found
- **Seeding pattern:** `persona_portfolio.py::link_persona_portfolios` / `_fetch_sample_positions` /
  `_reload_positions` — copies Sample positions onto a client + writes `EnrichedHolding` tags. Reuse
  directly; the seeder just needs to create the client + interactions first.
- **Client/notes creation:** `crm.py::_upsert_client(session, name, mandate)` (get-or-create) and the
  `Interaction(client_id, date, medium, rm_name, client_contact, note)` row pattern in `load_crm`.
- **Pipeline functions (all accept `client_id` to scope to one client):**
  `extract_dna(session, client_id)` (LLM) → `compute_fit(session, client_id)` (deterministic) →
  `compute_swaps(session, client_id)` (deterministic). `compute_drift` optional (model baseline has
  no drift by construction, so drift adds nothing — skip to keep the contrast pure).
- **Tagging:** `app.tags.instrument_tags(industry_group, region)` per copied position.
- **Endpoints (no change needed):** `portfolio.py` `/portfolio/fit`, `/portfolio/swaps`,
  `/portfolio/allocation`; `dna.py` `/clients/{id}/dna`. All key off `client_id`, so a simulated
  client is a first-class citizen automatically.
- **Admin orchestration precedent:** `admin.py::POST /admin/seed/persona-portfolios` already chains
  link→fit→swap→drift→rank — mirror its shape for the seeder route.

### Models / data
- `Client(name, mandate)` — only two required fields.
- `Interaction(client_id, date, medium, rm_name, client_contact, note)` — `note` is the DNA source.
- `ClientDNA` (exclusions/tilts/values as JSONB with `{text, tag, source_note_ids, confidence}`) +
  `Citation` rows (owner_type="client_dna" → CRM_NOTE) — produced by `extract_dna`.
- `MandateStrategy(mandate, sub_asset_class, target_weight)` — already the CIO target weights; the
  Sample positions already realise these weights, so weight-neutrality is structural, not computed.

### Dependencies Required
- Backend: SQLAlchemy async, existing LLM client (`json_chat`, Ollama/Gemma) for DNA. No new packages.
- DB: **no migration** — reuses `clients`, `interactions`, `positions`, `enriched_holdings`,
  `client_dna`, `swap_proposals`. (Confirm during impl that no UNIQUE on `clients.name` blocks
  re-seeding; `_upsert_client` is get-or-create so it is idempotent by name.)
- Runtime deps for the pipeline: `seed/portfolio` (Sample positions + CIO list + strategies) must
  have run first, since the baseline copies Sample positions and swaps draw on the CIO-BUY universe.

### Impact Assessment
#### Files to add / modify
- **New** `backend/app/loaders/simulate_client.py` (or extend `persona_portfolio.py`): a
  `seed_simulated_client(session, name, mandate, notes: list[dict]) -> dict` that creates the client,
  inserts interactions, copies Sample baseline positions, then runs extract_dna→compute_fit→compute_swaps
  scoped to the new `client_id`. Returns ids + counts.
- **Modify** `backend/app/routers/admin.py`: add `POST /admin/seed/simulate-client` accepting
  `{name, mandate, notes}`, calling the loader (mirrors `seed/persona-portfolios`). Demo-friendly.
- **No change** to `portfolio.py` / `dna.py` — TASK-065 consumes existing `/portfolio/fit` +
  `/portfolio/swaps` for model-vs-personalised. (Decision: prefer reuse over a `?baseline=model`
  variant — the model baseline already lives in `positions`, the personalised view in `swap_proposals`.)
- **New** `backend/tests/test_simulate_client.py`: seed→DNA→baseline→personalised + weight-neutrality.

#### Components Affected
- `admin.py` router — **LOW** (additive route).
- Portfolio/DNA endpoints — **NONE** (consume the new client unchanged).
- `persona_portfolio.py` — **LOW** if we factor `_reload_positions`/`_fetch_sample_positions` into a
  shared helper rather than copy-pasting.

#### API Changes
- `POST /admin/seed/simulate-client` — **new**, body `{name: str, mandate: "DEFENSIVE|BALANCED|GROWTH",
  notes: [{date?, medium?, rm_name?, client_contact?, note}]}` → `{client_id, dna_extracted, positions,
  swaps_proposed}`. No contract changes to existing endpoints.

#### Database Changes
- None (no schema/migration). New rows only.

### Implementation Checklist
- [ ] Reuse `persona_portfolio` copy-helpers (factor out `_fetch_sample_positions`/`_reload_positions`
      into a shared function) instead of duplicating position-copy logic.
- [ ] Reuse `_upsert_client` + `Interaction` insert pattern from `crm.py` for client + notes.
- [ ] Run `extract_dna`/`compute_fit`/`compute_swaps` scoped by `client_id` (do **not** re-run globally).
- [ ] Idempotent: re-seeding the same name wipes its positions/interactions/DNA before reload
      (match `_reload_positions` delete-then-insert).
- [ ] No fabricated holdings/prices — baseline holdings are real Sample positions; swap candidates are
      real CIO-BUY rows (grounding · no-fallbacks). Error loudly if `seed/portfolio` hasn't run.
- [ ] Self-documenting; structured logging mirroring `persona_portfolio.*` events.

### Risk Analysis
- **Risk Level:** LOW–MEDIUM
- **Main Risks:**
  - *DNA extraction needs the LLM (Ollama/Gemma) up* → seeder must surface a clear error if the model
    is unreachable rather than writing empty DNA (no-fallbacks). Mitigation: propagate `json_chat`
    failures; test can stub/seed DNA directly to keep the pipeline test LLM-independent.
  - *Weight-neutrality only holds if swaps preserve `(sub_asset_class, industry_group)`* — the engine
    already guarantees this; the test makes it an explicit assertion (compare per-SAC `current_chf`
    sums of baseline vs personalised — they must be identical since each swap is a 1:1 same-slot,
    same-`current_chf` replacement).
  - *`clients.name` collision with the four personas / Sample clients* → namespace simulated clients
    (e.g. `name` prefix `Sim:`), and confirm there is no DB UNIQUE that would reject re-seeds.

### Estimated Effort
- Original: M
- Adjusted: **S–M** — the "before/after" mechanic is already delivered by `compute_swaps`; net-new
  code is one loader + one admin route + tests. The realisation that no new fill engine is needed
  removes the largest chunk of the original M estimate.
