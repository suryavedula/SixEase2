# TASK-025: Portfolio and swap widgets

**Status:** IN-PROGRESS · **Epic:** EPIC-05 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Widgets: allocation donut, holdings table, drift bars (vs 2pp), sector treemap, per-holding fit heatmap, conflicts list, swap before-after with mandate-neutral proof.

## Acceptance Criteria
- [ ] multiple portfolio views from one dataset (18.2)
- [ ] swap before-after shows DNA reason + CIO view + weight unchanged
- [ ] registered in component registry

## Dependencies
TASK-003, TASK-024, TASK-041

## Refs
Requirements §18.2

---

## Technical Analysis (Auto-generated 2026-06-20)

### Dependency Status

| Task | Status | Impact on TASK-025 |
|---|---|---|
| **TASK-003** (React skeleton) | DONE | Full shell live: `AppShell`, `Header`, `Canvas`, `ActionCenter`, `InputDock`, `ThemeProvider`, Tailwind v4 CSS vars, port 15173. All patterns and theme tokens are usable now. |
| **TASK-024** (book view) | IN-PROGRESS (implemented) | `BookList.tsx` + `api/book.ts` + backend `/book` endpoint design are done. Backend per-client endpoints (`/portfolio/fit`, `/portfolio/swaps`) that TASK-025 consumes are already live — no blocking dependency. |
| **TASK-041** (component registry) | BACKLOG | The AC "registered in component registry" is technically gated on TASK-041. Mitigation: build all widgets as presentational/prop-driven components and export from `widgets/index.ts` as the pre-registry seam. TASK-041 wraps these exports with its typed registry and render protocol without touching widget internals. |

**Conclusion:** TASK-003 and TASK-024 are materially satisfied. TASK-025 can proceed fully; the registry AC will be confirmed once TASK-041 ships.

### Existing Resources Found

#### Components (reusable patterns)
- `DnaCard`, `DnaRadar`, `RelationshipTimeline`, `BookList` — 4 complete widget examples showing loading/error/ok state pattern, SVG rendering, Tailwind CSS vars, `apiGet` usage, `AbortController` cleanup.
- `DnaRadar.tsx` — SVG radar chart (polygon + rings + labels). Pattern reusable for `AllocationDonut` SVG arc segments.
- `BookList.tsx` — `FitBar` component (width-driven progress bar). Pattern reusable in `DriftBars` and `FitHeatmap`.
- `mandateBadgeClass()` — already defined in both `DnaCard.tsx` and `BookList.tsx`; should be extracted to a shared util (or duplicated per widget until a shared utils module is created).

#### Backend APIs (already live, no creation needed)
- `GET /clients/{id}/portfolio/fit` → `PortfolioFitResponse` with `portfolio_fit`, `mandate`, `holdings: [HoldingFit]`
  - `HoldingFit` fields: `position_id`, `issuer`, `security`, `industry_group`, `current_chf`, `tags`, `fit_score`, `conflicts`
  - **MISSING fields needed for TASK-025:** `sub_asset_class` (allocation / drift), `valor` (SIX price link)
- `GET /clients/{id}/portfolio/swaps` → `SwapProposalsResponse` with `positions: [PositionSwaps]`, `kept_positions: [KeptPosition]`
  - `PositionSwaps.candidates[].mandate_neutral` (bool) + `dna_reason` + `cio_view` + `fit_gain` — all fields needed for `SwapBeforeAfter` are already here.

#### Database (read-only)
- `positions` — has `sub_asset_class`, `industry_group`, `current_chf`, `valor`, `isin`, `issuer`, `security`
- `enriched_holdings` — has `fit_score: Float`, `conflicts: JSONB`, `tags: JSONB`
- `mandate_strategies` — has `mandate`, `sub_asset_class`, `target_weight (Numeric 5,2)` — needed for drift bars
- `swap_proposals` — has `mandate_neutral`, `dna_reason`, `cio_view`, `fit_gain`, `candidate_isin`, `candidate_valor`

#### Frontend utilities
- `api/client.ts` → `apiGet<T>(path, signal)` — the single fetch utility used by all widgets
- `src/index.css` CSS vars: `--color-blue`, `--color-green`, `--color-red`, `--color-amber`, `--color-purple`, `--color-teal`, `--color-muted`, `--color-dim`, `--color-border`, `--color-panel`, `--color-panel2`, `--color-panel3`
- Tailwind utility classes: `bg-blue/10 text-blue border-blue/20`, `animate-pulse`, `rounded-[14px]`, `border-border`, `bg-panel`, `text-muted`, `text-dim`

### Dependencies Required
- **Frontend packages:** none new — React, Tailwind v4, TypeScript already installed
- **Backend packages:** none new — SQLAlchemy, asyncpg already present
- **Database migrations:** none — all tables exist (`positions`, `enriched_holdings`, `mandate_strategies`, `swap_proposals`)
- **Docker services:** `postgres`, `backend`, `frontend` (all running)
- **Seeding order for full data:** `seed/portfolio` → `seed/tags` → `seed/crm` → `seed/dna` → `seed/fit` → `seed/swap`

### Impact Assessment

#### Files to Modify

- `backend/app/routers/portfolio.py`
  - Extend `HoldingFit` Pydantic model: add `sub_asset_class: str | None` and `valor: str | None`
  - Update `get_portfolio_fit()`: read `position.sub_asset_class` and `position.valor` into HoldingFit
  - Add new endpoint: `GET /clients/{id}/portfolio/allocation` → `AllocationResponse`

- `frontend/src/components/widgets/index.ts`
  - Export all 7 new widgets (acts as component registry seam pre-TASK-041)

#### Files to Create

**Backend:**
- None — all changes land in `backend/app/routers/portfolio.py`

**Frontend:**
- `frontend/src/api/portfolio.ts` — typed interfaces + `apiGet` fetchers for all 3 portfolio endpoints
- `frontend/src/components/widgets/AllocationDonut.tsx`
- `frontend/src/components/widgets/HoldingsTable.tsx`
- `frontend/src/components/widgets/DriftBars.tsx`
- `frontend/src/components/widgets/SectorTreemap.tsx`
- `frontend/src/components/widgets/FitHeatmap.tsx`
- `frontend/src/components/widgets/ConflictsList.tsx`
- `frontend/src/components/widgets/SwapBeforeAfter.tsx`

#### Components Affected
- `backend/app/routers/portfolio.py`: **MEDIUM** — additive extension to existing response model + new endpoint; no breaking changes
- `frontend/src/components/widgets/index.ts`: **LOW** — additive exports only
- Existing widgets (`DnaCard`, `BookList`, etc.): **NONE** — untouched

#### API Changes

**Extension (additive, non-breaking):**
- `GET /clients/{id}/portfolio/fit` — `HoldingFit` gains two optional fields (`sub_asset_class`, `valor`); existing consumers unaffected.

**New endpoint:**
```
GET /clients/{id}/portfolio/allocation

Response: AllocationResponse
  client_id: str
  client_name: str
  mandate: str
  total_chf: float
  sac_rows: list[SACRow]    # one row per sub_asset_class present in positions or mandate
  
SACRow:
  sub_asset_class: str
  current_chf: float         # sum of position.current_chf for this SAC
  current_pct: float         # current_chf / total_chf * 100
  target_pct: float          # from mandate_strategies.target_weight (0 if not in strategy)
  drift_pp: float            # current_pct - target_pct
  breach: bool               # |drift_pp| > 2.0
```

**Query strategy (no N+1):**
1. Load client → mandate
2. Single `SELECT positions GROUP BY sub_asset_class` for current weights
3. Single `SELECT mandate_strategies WHERE mandate = :mandate` for targets
4. Merge in Python; SAC rows present in positions but not strategy get `target_pct=0`.

#### Database Changes
None. No migrations required.

### Widget Design Notes

#### AllocationDonut (`AllocationDonut.tsx`)
- Props: `clientId: string`
- SVG arc segments for each sub-asset-class; colors from `--color-*` palette
- Click segment → highlights that SAC in DriftBars (if co-mounted)
- Data from: `GET /clients/{id}/portfolio/allocation`

#### HoldingsTable (`HoldingsTable.tsx`)
- Props: `clientId: string`
- Sortable columns: Issuer, Security, SAC, Industry Group, Current CHF, Fit Score
- Fit score cell colored: green (≥0.75), amber (0.25–0.74), red (0.0)
- Conflicts count badge on each row; click → expands inline conflict list
- Data from: `GET /clients/{id}/portfolio/fit`

#### DriftBars (`DriftBars.tsx`)
- Props: `clientId: string`
- Horizontal bar per sub-asset-class; center = target; bar fills left/right from center
- ±2pp band shown as a lighter region; breach → red bar, within → green/neutral
- Data from: `GET /clients/{id}/portfolio/allocation`

#### SectorTreemap (`SectorTreemap.tsx`)
- Props: `clientId: string` (or `holdings: HoldingFit[]` if caller already has fit data)
- SVG treemap, cells = industry_group sized by `current_chf`
- Color by fit score aggregate within that sector
- Simple sliced layout (no squarified algorithm needed for demo scale ~15 sectors)
- Data from: `GET /clients/{id}/portfolio/fit`

#### FitHeatmap (`FitHeatmap.tsx`)
- Props: `clientId: string`
- Grid of holding chips colored by fit_score; tooltip shows issuer + score + conflict tags
- Data from: `GET /clients/{id}/portfolio/fit`

#### ConflictsList (`ConflictsList.tsx`)
- Props: `clientId: string`
- Lists only holdings where `fit_score === 0.0`; shows exclusion tags, DNA reason
- "Propose swap" call-to-action linking to SwapBeforeAfter for that position
- Data from: `GET /clients/{id}/portfolio/fit` (filter on fit_score === 0)

#### SwapBeforeAfter (`SwapBeforeAfter.tsx`)
- Props: `clientId: string` (or `positionId?: string` to focus a single conflict)
- Two-panel layout: BEFORE (current holding, fit score, conflict tags) + AFTER (candidate, projected fit, fit gain)
- Mandate-neutral proof line: "Same sub-asset class — portfolio weight unchanged"
- DNA reason chip + CIO view badge (BUY + view text)
- Data from: `GET /clients/{id}/portfolio/swaps`

### Component Registry Integration (pre-TASK-041)

All widgets are exported from `widgets/index.ts`. When TASK-041 ships, it will:
1. Import these exports and register them by name in a typed `ComponentRegistry`
2. The render protocol (`{component: "AllocationDonut", props: {clientId}}`) will resolve via the registry without modifying widget internals.

TASK-025 design principle: **widgets are pure prop-driven presentational components; they do not know about the registry.**

### Implementation Checklist
Based on CLAUDE.md principles:
- [ ] Extend `HoldingFit` to add `sub_asset_class`, `valor` (additive, no migration)
- [ ] Create `GET /clients/{id}/portfolio/allocation` endpoint in `portfolio.py`
- [ ] Create `frontend/src/api/portfolio.ts` with typed interfaces for all 3 endpoints
- [ ] `AllocationDonut` — SVG donut; data from `/allocation`
- [ ] `HoldingsTable` — sortable table; data from `/fit`
- [ ] `DriftBars` — ±2pp band chart; data from `/allocation`
- [ ] `SectorTreemap` — SVG sliced treemap; data from `/fit`
- [ ] `FitHeatmap` — color grid; data from `/fit`
- [ ] `ConflictsList` — fit_score===0 filter; data from `/fit`
- [ ] `SwapBeforeAfter` — before/after panels with mandate-neutral + DNA reason + CIO view; data from `/swaps`
- [ ] All widgets: follow loading/error/ok state pattern from `DnaCard`/`BookList`
- [ ] All widgets: use `AbortController` cleanup in `useEffect`
- [ ] Export all 7 from `widgets/index.ts`
- [ ] Reuse existing Tailwind CSS vars — do NOT invent new color classes
- [ ] `mandateBadgeClass()` — reuse local copy (do not introduce a shared utils file unless explicitly tasked)
- [ ] Widgets are prop-driven and presentational — no global state, no context dependency

### Risk Analysis
- **Risk Level:** MEDIUM
- **Main Risks:**
  - *TASK-041 not started*: Registry AC is blocked. Mitigation: design widgets as exportable presentational units; registry seam is `widgets/index.ts`. Mark that AC as "ready, pending TASK-041."
  - *SVG treemap layout complexity*: Squarified treemap is non-trivial. Mitigation: use simple row-sliced layout (sort by CHF desc, row-fill by fixed height); sufficient at demo scale (~15 industry groups).
  - *HoldingFit extension breaks nothing*: The `portfolio/fit` response only adds optional fields (null-safe on existing callers). Risk: LOW.
  - *Allocation endpoint with no positions*: Client with no positions → `total_chf=0`, `sac_rows=[]`. Must return 200 with empty gracefully (same pattern as existing endpoints).
  - *7 widgets in one task*: Scope is significant but they all share the same data model and patterns. Mitigation: start with `HoldingsTable` + `ConflictsList` + `SwapBeforeAfter` (the demo-critical path) and add visual widgets after.

### Estimated Effort
- Original: M
- Adjusted: M-L
- Reason: 7 new widget files + 1 new API file + backend extension. The backend work is minimal (~40 lines). Frontend is dominated by SVG rendering for 4 charts (`AllocationDonut`, `DriftBars`, `SectorTreemap`, `FitHeatmap`). All patterns are established — no architecture decisions.

### Demo-Critical Widget Priority
1. `SwapBeforeAfter` — the key differentiator; maps to AC #2 directly
2. `HoldingsTable` — clearest portfolio view; needed for §18.2 AC #1
3. `ConflictsList` — surfaces the conflict → swap story
4. `DriftBars` — mandate integrity proof
5. `AllocationDonut` — visual anchor
6. `FitHeatmap` — portfolio quality at a glance
7. `SectorTreemap` — contextual sector view (lowest priority for MVP demo)
