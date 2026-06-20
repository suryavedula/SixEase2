# TASK-041: Component registry and render protocol

**Status:** DONE · **Epic:** EPIC-10 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20 · **Completed:** 2026-06-20

## Description
Build our own generative-UI core: a typed component registry mapping names to React widgets, a render protocol that validates {component, props} (zod/schema) and renders, with a safe fallback card on unknown/invalid.

## Acceptance Criteria
- [x] registry renders a validated widget spec
- [x] invalid/unknown spec falls back gracefully
- [x] widgets are presentational and prop-driven

## Dependencies
TASK-003 ✅ (done — React+Vite+Tailwind skeleton with Canvas, AppShell, InputDock, ActionCenter)

## Refs
Requirements §18 (V1), §18.3

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **Components (11 widgets, all reusable as-is):**
  - `AllocationDonut`, `BookList`, `ConflictsList`, `DnaCard`, `DnaRadar`, `DriftBars`, `FitHeatmap`, `HoldingsTable`, `RelationshipTimeline`, `SectorTreemap`, `SwapBeforeAfter`
  - All barrel-exported from `frontend/src/components/widgets/index.ts`
  - Uniform pattern: typed `{ clientId: string }` props, loading skeleton, error fallback card, main render — already presentational and prop-driven ✅

- **Shell:**
  - `Canvas.tsx` hardcodes all widgets directly; has TODO comment: *"The widget registry + command-driven render arrive in TASK-041"* — this is the integration point
  - `AppShell.tsx` owns `clientId` state lifted from `Canvas`; no changes needed
  - `InputDock.tsx` already defers command parsing to TASK-042/043 — no changes needed here

- **Services / APIs:** All widget data layers (`api/portfolio.ts`, `api/dna.ts`, `api/book.ts`, `api/alerts.ts`) are complete and stable. Registry doesn't touch them.

- **Utilities:** None relevant. Validation logic is new.

### Dependencies Required

- **Frontend packages to add:**
  - `zod` — spec validation. Not in `package.json` yet. Add via `npm install zod`.
- **Backend packages:** None — registry is purely frontend.
- **Database migrations:** None.
- **Docker services:** None.

### Impact Assessment

#### Files to Create (new)
- `frontend/src/registry/types.ts` — `WidgetSpec` type (`{ component: string; props: Record<string, unknown> }`); per-widget prop shape types
- `frontend/src/registry/registry.ts` — typed `Map<string, React.ComponentType<any>>` keyed by component name string; all 11 widgets registered
- `frontend/src/registry/WidgetRenderer.tsx` — validates spec via zod (unknown component → fallback; invalid props → fallback); renders matched widget; exports `FallbackCard` for reuse by TASK-042

#### Files to Modify
- `frontend/src/components/shell/Canvas.tsx` — replace hardcoded widget stack with a `WidgetRenderer` list driven by a local `WidgetSpec[]` state; the TASK-025 smoke-test UUID input seeds an initial spec list so existing test behaviour is preserved
- `frontend/package.json` — add `zod` runtime dependency

#### Components Affected
- `Canvas` — MEDIUM (internal render logic changes; props interface `{ clientId, onClientChange }` unchanged; external callers unaffected)
- All 11 widgets — LOW (zero changes; registry holds references, doesn't wrap them)
- `AppShell` — LOW (no changes needed; it just passes `clientId` to Canvas)

#### API Changes
None. The registry is a pure frontend concern.

#### Database Changes
None.

### Implementation Checklist
Based on CLAUDE.md principles:
- [ ] Reuse all 11 existing widgets as-is — no duplication or re-wrapping
- [ ] Add zod (runtime dep); no other new packages
- [ ] `WidgetSpec` is a plain discriminated union (`{ component: string; props: Record<string, unknown> }`) — keep it flat; do NOT over-engineer per-widget zod schemas for V1 (validate `component` presence and registry membership; props forwarded as-is)
- [ ] Fallback card: matches existing widget shell style (`rounded-[14px] border border-border bg-panel p-4`) with component name + reason displayed
- [ ] `Canvas.tsx` smoke-test path preserved: UUID input → seeds `[{ component: "HoldingsTable", props: { clientId } }, ...]` spec list
- [ ] Follow SOLID principles — registry is a single-responsibility map; renderer is a single-responsibility validator+dispatcher
- [ ] Write self-documenting code (no comments beyond the task reference line)

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - Props type safety: zod can't statically infer per-widget prop shapes at runtime without per-widget schemas. **Mitigation:** V1 validates only that `component` is a registered key; prop types are caught by TypeScript at call sites. Per-widget prop schemas can be added in a follow-up.
  - Canvas smoke-test regression: current UUID → hardcoded widget stack may break if Canvas is rewritten carelessly. **Mitigation:** preserve the same spec-seeding logic in the TASK-025 path, just driven through specs instead of hardcoded JSX.

### Estimated Effort
- **Original:** M
- **Adjusted:** M (unchanged — 3 new files, 2 file edits, no backend work)
- **Reason:** Well-scoped; all 11 widgets are already prop-driven; the pattern is clear from TASK-003 comments.
