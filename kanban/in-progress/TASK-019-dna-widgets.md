# TASK-019: DNA widgets

**Status:** IN-PROGRESS · **Epic:** EPIC-04 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Frontend widgets rendering ClientDNA in multiple views: DNA card, value-axis radar, relationship timeline. Each shows sources on expand.

## Acceptance Criteria
- [ ] DNA card, radar, timeline render from API
- [ ] sources expandable (UI-8)
- [ ] registered in the component registry

## Dependencies
TASK-003, TASK-018, TASK-041

## Refs
Requirements §18.2, UI-8

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **`GET /clients/{client_id}/dna` endpoint (TASK-018, in-progress)** — `backend/app/routers/dna.py`
  Fully defined contract: returns `DNAResponse` with `values`, `exclusions`, `tilts`, `life_events`,
  `promises`, `style_profile`, `business_context`, `family_context`, `temperament`, `mandate`,
  `version`, and a hydrated `sources[]` array. Each source has `{id, date, medium, note}`.
  Each JSONB attribute item carries `source_note_ids[]` for cross-referencing back to `sources[]`.
- **`apiGet<T>()` base client** — `frontend/src/api/client.ts`
  Generic typed fetch wrapper. New `frontend/src/api/dna.ts` module can follow the pattern of
  `frontend/src/api/health.ts` exactly.
- **App shell Canvas seam** — `frontend/src/components/shell/Canvas.tsx`
  Canvas comment: *"the widget registry + render protocol arrive in TASK-041"*. The central canvas
  is where widget output will land once the registry is wired.
- **Theme tokens** — `frontend/src/index.css`
  Full palette available as Tailwind utilities: `bg-panel`, `bg-panel2`, `bg-panel3`,
  `border-border`, `text-muted`, `text-dim`, accent colors `text-blue`, `text-green`, `text-red`,
  `text-amber`, `text-purple`, `text-teal`. `--radius-card: 14px`.
- **`AppShell` grid** — `frontend/src/components/shell/AppShell.tsx`
  Existing component import pattern — add widgets to `frontend/src/components/widgets/`.
- **No chart library installed** — `frontend/package.json` has only `react`, `react-dom`,
  `tailwindcss`, `@tailwindcss/vite`, `@vitejs/plugin-react`, TypeScript. The radar chart must
  either add a library (recharts recommended — tiny, React-native SVG) or use a pure SVG polygon.
  Given only one radar widget, a pure SVG implementation avoids a new dependency.

### Dependencies Required

- Frontend packages: **none new** if radar is pure SVG; optionally `recharts` (~50KB gz) if chart
  needs reuse in TASK-025 (portfolio widgets). Defer to implementation decision.
- Backend packages: none.
- Database migrations: none — all schema is live (TASK-004/018).
- Docker services: backend + postgres (already running).

### API Client Contract

```typescript
// frontend/src/api/dna.ts
import { apiGet } from "./client";

export interface DnaSource { id: string; date: string | null; medium: string | null; note: string | null; }
export interface DnaItem   { text: string; tag: string | null; source_note_ids: string[]; confidence: number; }

export interface DnaResponse {
  id: string; client_id: string; client_name: string;
  mandate: string | null; version: number;
  values: DnaItem[] | null; exclusions: DnaItem[] | null;
  tilts: DnaItem[] | null; life_events: DnaItem[] | null;
  promises: DnaItem[] | null;
  style_profile: Record<string, unknown> | null;
  business_context: string | null; family_context: string | null; temperament: string | null;
  sources: DnaSource[];
  created_at: string; updated_at: string;
}

export function getClientDna(clientId: string, signal?: AbortSignal): Promise<DnaResponse> {
  return apiGet<DnaResponse>(`/clients/${clientId}/dna`, signal);
}
```

### Impact Assessment

#### Files to Create
- `frontend/src/api/dna.ts` — typed API client for `/clients/{id}/dna`
- `frontend/src/components/widgets/DnaCard.tsx` — card widget: mandate badge, values/exclusions/tilts/promises chips, expandable source drawer (UI-8)
- `frontend/src/components/widgets/DnaRadar.tsx` — value-axis radar: pure SVG polygon over 5–6 DNA dimensions (values count, exclusions count, tilts count, temperament, style scores)
- `frontend/src/components/widgets/RelationshipTimeline.tsx` — chronological list of `sources[]` interactions with date, medium, note excerpt; expandable to full note
- `frontend/src/components/widgets/index.ts` — barrel export (consumed by TASK-041 registry)

#### Files to Modify
- None mandatory until TASK-041 lands. The `Canvas.tsx` seam stays intact; widgets are
  standalone prop-driven components. They will be registered in the component registry as
  `{name: "DnaCard", component: DnaCard}` entries once TASK-041 delivers the registry.

#### Components Affected
- `Canvas.tsx`: LOW — no change; widgets render inside it once the registry dispatches them
- `AppShell.tsx`: LOW — no change; new `widgets/` directory is additive
- Backend: NONE — read-only consumer of existing `GET /clients/{id}/dna`

#### API Changes
- None. Read-only consumption of TASK-018 endpoint.

#### Database Changes
- None.

### Widget Specs

**DnaCard** (`{clientId: string}`)
- Header: client name, mandate badge (BALANCED/DEFENSIVE/GROWTH), version pill
- Sections: Values · Exclusions · Tilts · Promises — each rendered as chip list
- Each chip shows tag (if present) or text truncated; hover shows full text
- "Sources" toggle at footer expands list of `sources[]` (date · medium · note excerpt) — UI-8
- Loading skeleton; 404 → "DNA not yet extracted" prompt

**DnaRadar** (`{dna: DnaResponse}`)
- Pure SVG radar/spider chart, 5 axes: Values, Exclusions, Tilts, Life Events, Promises
- Score = count of items per dimension (normalised to max across dims)
- Polygon fill with accent-blue, grid lines in `--color-border`
- Axis labels in `--color-muted`; no external chart library needed

**RelationshipTimeline** (`{sources: DnaSource[]}`)
- Vertical timeline sorted by date desc
- Each row: date pill + medium badge + note text (truncated 120 chars)
- Click row to expand full note text
- Empty state if no sources

### Implementation Checklist
Based on CLAUDE.md principles:
- [ ] `frontend/src/api/dna.ts` — typed wrapper following `health.ts` pattern
- [ ] `DnaCard.tsx` — prop-driven (`clientId`); fetches own data via `getClientDna`; loading + error states
- [ ] `DnaRadar.tsx` — prop-driven (`dna: DnaResponse`); pure SVG; no new package
- [ ] `RelationshipTimeline.tsx` — prop-driven (`sources: DnaSource[]`); expandable rows (UI-8)
- [ ] `widgets/index.ts` — barrel export for TASK-041 registry integration
- [ ] All three widgets use only existing Tailwind tokens (`bg-panel`, `border-border`, etc.)
- [ ] `DnaCard` source expand/collapse is the UI-8 pattern — toggle state, not a modal
- [ ] Render in Canvas during dev (manual import) to verify layout; remove stub on registry handoff
- [ ] `DnaRadar` axis labels do not overflow card width at 326px (Action Center width)
- [ ] No duplicate components — check `frontend/src/components/` before adding any utility

### Risk Analysis
- **Risk Level**: MEDIUM
- **Main Risks**:
  - *TASK-018 still in-progress*: the DNA endpoint may not be seeded with real data yet →
    mitigate by using `POST /admin/seed/dna` to populate test data; the contract is stable.
  - *TASK-041 (registry) still in backlog*: the "registered in registry" AC cannot be completed
    until TASK-041 ships → build widgets as fully prop-driven standalones; AC #3 completes when
    TASK-041 picks up the barrel export. Do not block on it for the widget implementations (AC #1, #2).
  - *Radar SVG overflow at small canvas widths*: set `viewBox` with `preserveAspectRatio` so it
    scales; test at both 326px (Action Center) and full-width canvas.
  - *Source note text length*: CRM notes can be multi-paragraph → truncate at 120 chars with
    expand toggle; never render raw HTML.

### Estimated Effort
- Original: M
- Adjusted: M (unchanged)
- Reason: Three focused prop-driven widgets + one API module. No new backend work. The only
  complexity is the SVG radar and the source expand pattern (UI-8). TASK-041 blocker for AC #3
  is non-blocking for implementation.
