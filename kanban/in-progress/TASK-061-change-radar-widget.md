# TASK-061: ChangeRadar widget — top-10, impacted-client expand, batch fix

**Status:** IN-PROGRESS · **Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20
**Epic:** EPIC-08 · **Parent:** TASK-058 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20

## Description
Frontend widget that renders the top-10 book-wide changes from TASK-059. Each row: type badge
(news / internal / email), headline, one grounded "why it matters" line, source + timestamp,
and an impact bar. Expands to the impacted-client list — each with exposure (CHF/%), DNA
relevance, drift caused — and a per-client action plus a batch action for the whole event.

```
📉  Nestlé downgraded to SELL · CIO flip · 2h ago        [impact ███████░]
    Hits 23 clients · CHF 6.1M exposed · 4 now breach drift
    ▸ client list → each: CHF/% · DNA note · [Swap] [Task] [Email]
    ⚡ Batch: swap all 23 → CIO-BUY replacement   (review, then per-client)
```

## Acceptance Criteria
- [x] New `ChangeRadar` widget registered in registry.ts; refetches on open
- [x] Top-10 ranked by aggregate impact; type badges for news / internal / email
- [x] Row expands to impacted-client list with exposure + DNA + drift, each citing its source
- [x] Per-client actions: convert-to-task, draft email (reuse EmailDraft), swap (TASK-021)
- [x] Batch action across all impacted clients, respecting each client's DNA/exclusions
- [x] Human-in-the-loop: nothing sent automatically; every action ends in RM review
- [x] Loading/error/empty states; no fabricated numbers (all from TASK-059 payload)

## Implementation (2026-06-20)
**New** `frontend/src/api/radar.ts` — `ImpactedClient`/`RadarEvent`/`RadarResponse` + `getRadar(limit)`
(mirrors `api/alerts.ts`; reuses `apiGet`). **New** `frontend/src/components/widgets/ChangeRadar.tsx`
— cloned from `ClientBook.tsx`'s state-machine: top-N rows with `badgeFor(source)` (news/email/
internal), grounded "why it matters", relative timestamp, impact bar (`impact_score / events[0].impact_score`,
relative — never fabricated), `expandedId` → impacted-client list (CHF/%, `dna_note`, signed
`drift_caused`pp), per-client **Swap**→PortfolioView / **Task**→`convertAlertToTask` (disabled when no
`alert_id`) / **Email**→EmailDraft, a two-step-confirm **batch** that fans `convertAlertToTask` over
impacted clients (created/skipped/failed summary; skips no-alert clients), and an **unresolved**
section (no-fallbacks). **Wired** into `index.ts` / `registry.ts` / `tileLayout.ts` (`"wide"`).

**Verification:** isolated `tsc` of the two new files = 0 errors (the project-wide build is red only
from an unrelated, untracked WIP shell file `CanvasTile.tsx`). Data path live-checked: seeded
`alerts → drift → radar`, `GET /radar?limit=10` returns 9 events + 1 unresolved with every rendered
field populated (`alert_id` present, `exposure_pct` as %, negative `drift_caused`). Fixed a sign bug
(negative drift was rendering "+-17.3pp"). Browser walkthrough deferred — shell is mid-edit in
parallel so `vite build`/dev is currently unstable through no fault of this widget.

## Technical Approach
### Reuse
`WidgetContainer`, `CanvasActions`, `EmailDraft`, alerts→task convert, registry pattern
(mirror Client360/ClientBook wiring).
### New
`ChangeRadar.tsx` + api client for the `/radar` endpoint + batch-action confirm flow.

## Dependencies
TASK-059 (radar API) · TASK-021 (swap) · TASK-041/042 (registry/command-bar) · TASK-035 (alert convert)

## Refs
frontend/src/registry/registry.ts · frontend/src/components/widgets/Client360.tsx · docs/Requirements.md §UI

## Technical Analysis (Auto-generated 2026-06-20)

### Headline — this is a frontend-only task
The backend is **already done**: `GET /radar?limit=N` (`backend/app/routers/radar.py`) returns the
full payload. No backend, no DB, no migration. The widget consumes it and wires per-client + batch
actions out of existing API clients.

**`GET /radar?limit=10` → `RadarResponse`** (verbatim field list to mirror in TS):
- `events: RadarEvent[]` (resolved, ranked `impact_score` DESC), `unresolved: RadarEvent[]`, `total: int`
- `RadarEvent`: `id, action, entity_key, entity_type (instrument|sector|client|macro),
  entity_label, source (news|cio|drift|dna|email), event_ts, magnitude, impact_score,
  client_count, total_exposure_chf, impacted_clients[], suggested_batch_action, sources, unresolved_reason`
- `ImpactedClient`: `client_id, client_name, exposure_chf, exposure_pct, drift_caused, dna_note,
  suggested_action, alert_id, swap_candidate`
The payload already carries everything the mock row needs — **no number is computed client-side** (G2).

### Existing Resources Found
- **API base:** `apiGet<T>` in `frontend/src/api/client.ts` (`VITE_API_BASE_URL`, throws on non-2xx,
  AbortSignal). Module pattern: one `api/{domain}.ts` per domain (see `api/alerts.ts`).
- **Chrome:** `WidgetContainer` (`title`, `source`, `badges`, `children`).
- **Canvas dispatch:** `useCanvasActions().addSpecs([{component, props}])` to append widgets.
- **Per-client actions (all exist — AC items map 1:1):**
  - convert-to-task → `convertAlertToTask(clientId, alertId)` in `api/alerts.ts` (uses `ImpactedClient.alert_id`).
  - draft email → `addSpecs([{component:"EmailDraft", props:{clientId}}])` (`EmailDraft` loads latest draft).
  - swap → `addSpecs([{component:"PortfolioView", props:{clientId}}])` (PortfolioView surfaces
    `/portfolio/swaps`; `ImpactedClient.swap_candidate` is already DNA-filtered in the payload).
- **Patterns to mirror:** list+row from `ClientBook.tsx`; fetch/loading/error/empty state-machine +
  AbortController from `Client360.tsx`/`VoiceNoteWidget.tsx`; registry wiring from any widget.

### Dependencies Required
- Frontend packages: none new (React, existing api/client, lucide icons already in use).
- Backend/DB: none. **Runtime data dep:** radar must be seeded — `seed/alerts → seed/drift →
  scan/news → seed/radar` (admin POSTs). If empty, render the empty state (don't fabricate).

### Impact Assessment
#### Files to add / modify
- **New** `frontend/src/api/radar.ts` — `ImpactedClient`/`RadarEvent`/`RadarResponse` interfaces +
  `getRadar(limit = 10, signal?) → apiGet<RadarResponse>(\`/radar?limit=${limit}\`, signal)`.
- **New** `frontend/src/components/widgets/ChangeRadar.tsx` — top-10 rows (type badge, headline,
  one grounded "why it matters", source+timestamp, impact bar), local `expandedEventId` state →
  impacted-client list with exposure (CHF/%) + `dna_note` + `drift_caused`, per-client action
  buttons, and a batch-action confirm flow. Plus an `unresolved` section (no-fallbacks visibility).
- **Modify** `frontend/src/components/widgets/index.ts` — `export { ChangeRadar } from "./ChangeRadar"`.
- **Modify** `frontend/src/registry/registry.ts` — import + `["ChangeRadar", ChangeRadar]` map entry.
- **Modify** `frontend/src/registry/tileLayout.ts` — `ChangeRadar: "wide"` (dense rows + expand → wide).

#### Components Affected
- registry / index / tileLayout — **LOW** (additive entries).
- `EmailDraft`, `PortfolioView`, alerts-convert — **NONE** (consumed via `addSpecs`/api, unchanged).

#### API / Database Changes
- None. GET `/radar` already registered in `main.py`.

### Key implementation decisions
- **Type badge** (ticket says news / internal / email): map `event.source` → `news`→news,
  `email`→email, `cio|drift|dna`→**internal** (single helper; also usable for the icon 📉/🏦/✉️).
- **Impact bar** width = `event.impact_score / events[0].impact_score` (events sorted DESC, so
  `events[0]` is the max — relative bar, never a fabricated absolute).
- **"Why it matters"** = `event.action` + entity_label (event-level); per client = `dna_note`.
- **Batch action = review, then per-client** (human-in-the-loop): clicking "Batch swap all N" opens
  a confirm/review list (e.g. fans `convertAlertToTask` per impacted client, or appends each client's
  PortfolioView) — **never** an outward/irreversible action. `swap_candidate` is already
  DNA/exclusion-filtered server-side, satisfying "respecting each client's DNA/exclusions".
- **Refetch on open:** fetch in `useEffect` on mount — each canvas insertion is a fresh mount.

### Implementation Checklist
- [ ] Reuse `WidgetContainer` + `apiGet` + `addSpecs`; do NOT add a new fetch wrapper.
- [ ] Reuse `convertAlertToTask` / `EmailDraft` / `PortfolioView` for the three per-client actions.
- [ ] Mirror the `Client360`/`VoiceNoteWidget` AbortController state-machine (loading/error/empty/ok).
- [ ] Render `unresolved` events explicitly; no fabricated numbers (all from payload · G2).
- [ ] Human-in-the-loop: batch action ends in RM review; nothing sent/executed automatically.
- [ ] Self-documenting; match existing Tailwind tokens (`bg-panel2`, `text-muted`, `text-dim`).

### Risk Analysis
- **Risk Level:** LOW–MEDIUM (frontend-only, contract already fixed).
- **Main Risks:**
  - *Empty radar in demo* (seed chain not run) → ship a clear empty state + the unresolved section;
    never fall back to fake events.
  - *Per-client "draft email" lands on EmailDraft empty state* when no draft has been assembled for
    that client → acceptable (RM triggers a render there); note in UI copy rather than hiding it.
  - *Batch action overreach* → keep it strictly review-then-per-client; no bulk send/trade. Mitigate
    with an explicit confirm step and per-client cards, not a single fire-all button.

### Estimated Effort
- Original: M
- Adjusted: **M** — frontend-only and the contract is fixed, but the expand list + three per-client
  actions + batch confirm flow + type-badge/impact-bar logic is real work. No backend offsets it.
