# TASK-065: Before/After portfolio widget — "values honoured, within CIO"

**Status:** IN-PROGRESS · **Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20
**Epic:** EPIC-10 · **Parent:** TASK-062 · **Priority:** P1 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20

## Description
The screen that sells the whole product. A before/after portfolio view whose **headline makes two
claims at once**: *your values are now honoured* (the personalisation) **and** *we never left CIO*
(the discipline). Rebuilds/consolidates the deleted `SwapBeforeAfter.tsx` into one widget that
serves both modes — existing client (current → swapped) and simulated client (model → personalised,
TASK-064).

Layout, leading with values+CIO, not the raw instrument swaps:
```
✅ Values honoured · 100% within CIO strategy
   Removed 2 holdings conflicting with your "no-fossil" exclusion · tilted to neuro-research
   ┌── Strategy unchanged ──────────────┐   Portfolio fit  0.52 → 0.81
   │ sub-asset-class weights identical  │   3 conflicts resolved
   │ (mandate-neutral proof bar)        │   every swap = CIO-BUY
   └────────────────────────────────────┘
   ▸ Instrument deltas: Issuer → Candidate · dna_reason · CIO view · fit-gain
   [Approve for RM review]  [Reject]
```

## Acceptance Criteria
- [ ] New before/after widget registered in registry.ts; reuses `WidgetContainer`/`CanvasActions`
- [ ] Headline asserts **values honoured + within-CIO** with resolved-conflict count
- [ ] Mandate-neutral proof: sub-asset-class weights shown identical before/after
- [ ] Fit delta (portfolio_fit before → after) and per-swap deltas (dna_reason, CIO view, fit-gain)
- [ ] Two data modes: existing-client (`/swaps`) and simulated-client model-vs-personalised (TASK-064)
- [ ] Human-in-the-loop: Approve flags for RM only; no auto-trade
- [ ] Loading/error/empty states; all numbers from payload, none fabricated (grounding)

## Technical Approach
### Reuse
`PortfolioView.tsx` current before/after logic, deleted `SwapBeforeAfter.tsx` (git history) for
the delta-card pattern, `WidgetContainer`, `CanvasActions`, registry wiring (mirror Client360).
### New
`BeforeAfter.tsx` (working name) + mode switch (existing vs simulated) + weight-neutrality bar.

## Dependencies
TASK-063 (radar entry point) · TASK-064 (simulated baseline) · TASK-021 (swap) · registry/command-bar

## Refs
frontend/src/components/widgets/PortfolioView.tsx · git history: SwapBeforeAfter.tsx ·
frontend/src/registry/registry.ts · docs/Requirements.md §UC-4, §UI

## Technical Analysis (Auto-generated 2026-06-20)

### Key realisation — both modes are the SAME two endpoints, mode is copy-only
TASK-064 (done) deliberately **did not** add a `?baseline=model` variant. A simulated client is a
first-class `Client`; its house-model baseline lives in `positions` (zero-drift Sample book) and its
personalised "after" lives in `swap_proposals`. So **both data modes are served by the existing
`GET /clients/{id}/portfolio/{fit,swaps,allocation}`** with only a `clientId`:
- **before** = `getPortfolioFit().holdings` (existing-client: drifted current · simulated: zero-drift model)
- **after** = `getPortfolioSwaps().positions[].candidates[0]` (best-fit CIO-BUY per conflict slot)
- **mode** (`existing` vs `simulated`) changes **labels/headline copy only** ("Current → Swapped" vs
  "Model → Personalised"). The fetch is identical. ⇒ Net-new frontend = one widget + wiring. No new API,
  no migration, no backend change.

### Existing Resources Found
- **API (no change):** `api/portfolio.ts` — `getPortfolioFit`/`getPortfolioSwaps`/`getPortfolioAllocation`
  + all types (`PortfolioFitResponse`, `SwapProposalsResponse`, `AllocationResponse`, `PositionSwaps`,
  `SwapCandidate`, `KeptPosition`, `SACRow`). Reuse verbatim.
- **Chrome:** `WidgetContainer` (titled panel + provenance badge), `SourcesFooter`/`DisplaySource`
  (per-swap DNA/CIO citations — used by the deleted `SwapBeforeAfter`).
- **HITL pattern:** `PortfolioView.tsx` local `decision` state + Approve/Reject buttons + "queued for RM
  review / nothing executed automatically" footer — copy this exactly (no auto-trade).
- **Before→After visual:** deleted `SwapBeforeAfter.tsx` (git `HEAD:`) — `SwapCard` (red BEFORE / green
  AFTER panels + arrow), `ScoreDot`/`fitColor`, the **proof strip** (mandate-neutral chip + DNA + CIO
  rows), `KeptCard` (no-compliant-swap, surfaced not dropped), and the 404→"run seed/swap" hint.
- **Canvas append:** `useCanvasActions().addSpecs([{component, props}])` (Client360's "Deep Dive" button)
  — the radar/Client360 entry points push the widget onto the canvas with `mode` set in-app.
- **Wiring precedent:** mirror `Client360` — `widgets/index.ts` export, `registry.ts` import+`Map` entry,
  orchestrate `_CLIENT_SCOPED`+`_CATALOG`.

### Dependencies Required
- Frontend packages: none new (`lucide-react`, Tailwind tokens, `cn` all present).
- Backend packages / DB migrations / Docker services: **none**.
- Runtime data deps: `POST /admin/seed/portfolio` then `POST /admin/seed/swap` (existing mode) and
  `POST /admin/seed/simulate-client` (simulated mode, TASK-064) must have run for live data.

### Impact Assessment
#### Files to Modify
- `frontend/src/components/widgets/BeforeAfter.tsx` — **NEW** widget (working name; TASK-062 open
  decision "Before/After" vs "Fit Studio" — keep `BeforeAfter` unless renamed before demo).
- `frontend/src/components/widgets/index.ts` — export `BeforeAfter`.
- `frontend/src/registry/registry.ts` — import + register `["BeforeAfter", BeforeAfter]`.
- `backend/app/routers/orchestrate.py` — add `"BeforeAfter"` to `_CLIENT_SCOPED` + a `_CATALOG` line so
  the model can summon it from chat (props get stripped to `{clientId}` ⇒ chat path renders existing mode).

#### Components Affected
- `registry.ts` / `index.ts` — **LOW** (additive).
- `orchestrate.py` `_CLIENT_SCOPED`/`_CATALOG` — **LOW** (additive; note prop-stripping below).
- `PortfolioView.tsx` — **NONE** (its inline AI-Swap card overlaps this widget; do **not** delete it under
  this task — consolidation, if any, is a follow-up). `SwapBeforeAfter` stays deleted; we rebuild, not restore.

#### API Changes
- None. Consumes existing endpoints unchanged.

#### Database Changes
- None.

### The two genuinely-new design points
1. **`mode` cannot arrive via chat.** Orchestrate forces client-scoped widget props to exactly
   `{clientId}` (orchestrate.py:463), so the model can never set `mode`. ⇒ `mode?: "existing" | "simulated"`
   defaults to `"existing"`; the **simulated** entry point is the radar/seed flow pushing
   `addSpecs([{component:"BeforeAfter", props:{clientId, mode:"simulated"}}])` in-app. Chat/orchestrate
   always renders existing mode — acceptable (simulated is a launched demo, not free-text).
2. **Projected portfolio-fit ("after") is not returned by any endpoint.** `fit.portfolio_fit` is the
   "before"; there is no server-side after-fit. Compute it **client-side, deterministically** from payload
   numbers (consistent with PortfolioView computing weights and SwapBeforeAfter computing
   `current_fit_score + fit_gain`): replace each swapped holding's fit with `current_fit_score + best.fit_gain`
   and re-aggregate. **RISK — must match `loaders/fit.py`'s `portfolio_fit` formula** (confirm it is the
   exposure-weighted mean of holding `fit_score`s before implementing) or before/after will use
   inconsistent maths. If the formula can't be faithfully replicated, fall back to showing only
   resolved-conflict count + per-swap fit-gains and **omit a single headline fit number** rather than
   display a fabricated/inconsistent one (no-fallbacks). Recommend confirming `fit.py` first.

### Implementation Checklist
- [ ] Reuse `WidgetContainer`/`SourcesFooter`/`useCanvasActions`; rebuild `SwapCard`+proof-strip+`KeptCard`
      from git-history `SwapBeforeAfter.tsx` (don't restore the file — fold into the new widget).
- [ ] One fetch path for both modes (`fit`+`swaps`+`allocation`, Promise.all w/ graceful null like Client360);
      `mode` prop drives copy only.
- [ ] Headline asserts **values honoured + 100% within CIO** + resolved-conflict count (`positions.length`);
      "every swap = CIO-BUY" (engine-guaranteed); surface `kept_positions` (conflicts w/ no swap) — never drop.
- [ ] Mandate-neutral proof bar from `allocation.sac_rows` — identical before/after by construction
      (TASK-064 `_assert_weight_neutral`); show the SAC weights and the unchanged assertion.
- [ ] Fit delta `portfolio_fit before → after` per the §"design points" decision (confirm `fit.py` first).
- [ ] Per-swap deltas: issuer → candidate · `dna_reason` · `candidate_cio_view` · `fit_gain`.
- [ ] HITL: local Approve-for-RM-review / Reject (copy PortfolioView `decision` state); **no auto-trade**.
- [ ] Loading skeleton · error (404 → "run seed/swap" hint) · empty ("holdings already align") states.
- [ ] All numbers from payload — none fabricated (grounding); per-swap DNA/CIO citations via `SourcesFooter`.
- [ ] Register in `index.ts` + `registry.ts`; add to orchestrate `_CLIENT_SCOPED` + `_CATALOG`.

### Risk Analysis
- **Risk Level:** LOW–MEDIUM
- **Main Risks:**
  - *Projected after-fit consistency* (see design point 2) → confirm/replicate `fit.py` aggregation, else
    omit the single fit number. **Primary risk.**
  - *TASK-063 (radar entry point) still BACKLOG* → it only gates book-sweep navigation INTO the widget, not
    the widget itself. Build/test now via the command bar (existing mode) + the seeded `[SIMULATED] Clara
    Bauer` client (simulated mode, TASK-064 done). Wire the radar→widget jump when 063 lands.
  - *Overlap with PortfolioView's inline swap card* → both can render swaps; keep them distinct under this
    task (PortfolioView = analysis; BeforeAfter = the pitch screen). Flag consolidation as a follow-up.
  - *Widget name not finalised* (TASK-062 open decision) → ship as `BeforeAfter`, easy single-point rename.

### Estimated Effort
- Original: M
- Adjusted: **S–M** — both modes collapse onto the existing endpoints (mode = copy only) and the visual
  pattern already exists in git history; net-new is one widget + 3 wiring edits. The only real work is the
  projected-fit decision and the values+CIO headline composition.
