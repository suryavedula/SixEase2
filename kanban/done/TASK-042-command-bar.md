# TASK-042: Command bar (slash/NL/voice)

**Status:** DONE · **Epic:** EPIC-10 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20 · **Completed:** 2026-06-20

## Description
Input dock: slash commands, natural language, scope tabs (All/Clients/Market/Documents/Analysis), quick-command chips, hide-input focus mode; sends requests to the orchestrator.

## Acceptance Criteria
- [x] slash + NL commands dispatch to orchestrator
- [x] chips and scope tabs work
- [x] renders returned widgets into the canvas

## Dependencies
TASK-003 ✅ (done — React+Vite+Tailwind skeleton with Canvas, AppShell, InputDock, ActionCenter)
TASK-041 🔄 (in-progress — registry + WidgetRenderer + WidgetSpec type; Canvas will accept `specs: WidgetSpec[]`)
TASK-043 ⏳ (backlog — backend `/orchestrate` endpoint; TASK-042 stubs this until it lands)

## Refs
Requirements §17 UI-1, §18.3

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **`InputDock.tsx`** (`frontend/src/components/shell/InputDock.tsx`):
  - Shell, local `value` state, and quick-command chips already exist.
  - `submit()` is a no-op (`console.info`). Explicitly deferred to TASK-042/043 by comment.
  - 4 hardcoded chip strings. Voice button is a placeholder emoji (TASK-046).
  - **Reuse as-is**: expand rather than rewrite; all chrome stays, logic is additive.

- **`AppShell.tsx`** (`frontend/src/components/shell/AppShell.tsx`):
  - Already owns `clientId: string | null` state lifted from Canvas.
  - Renders `<InputDock />` with no props currently.
  - **Integration point**: lift `specs: WidgetSpec[]` state here; pass `onAddSpecs` down to InputDock and `specs` down to Canvas (mirrors the `clientId` / `onClientChange` pattern already established).

- **`Canvas.tsx`** (`frontend/src/components/shell/Canvas.tsx`):
  - Currently hardcodes all widgets directly + has UUID smoke-test form.
  - TASK-041 is converting this to be spec-driven (`WidgetSpec[]` state). After TASK-041, Canvas accepts `specs` + `onClear` props.
  - **Coordination**: TASK-042 state wiring must compose with TASK-041's Canvas refactor — spec state is lifted to AppShell so both can access it cleanly.

- **`api/client.ts`** (`frontend/src/api/client.ts`):
  - Provides `apiPost<T>()` already. The new `api/orchestrate.ts` just calls it.
  - No changes to `client.ts` needed.

- **No orchestrator router exists yet** in `backend/app/routers/` — that is TASK-043. TASK-042 provides a stub that falls back to local slash-command resolution so the frontend is testable before TASK-043 lands.

### Dependencies Required

- **Frontend packages:** None new. `zod` is being added by TASK-041 (for the registry); `api/orchestrate.ts` uses plain `fetch`/`apiPost`.
- **Backend packages:** None — the backend orchestrator EP is TASK-043's scope.
- **Database migrations:** None.
- **Docker services:** None.

### Impact Assessment

#### Files to Create (new)
- `frontend/src/api/orchestrate.ts` — `POST /orchestrate` client returning `WidgetSpec[]`; falls back to local slash-command stub while TASK-043 is not yet available.

#### Files to Modify
- `frontend/src/components/shell/InputDock.tsx` — add scope tabs, command parsing, orchestrator dispatch, loading state, hide-input toggle. Chips wired to real dispatch.
- `frontend/src/components/shell/AppShell.tsx` — lift `specs: WidgetSpec[]` and `setSpecs` state here; pass `onAddSpecs` to InputDock and `specs` to Canvas. Coordinates with TASK-041's Canvas refactor.
- `frontend/src/components/shell/Canvas.tsx` — accept `specs` + `onClearSpecs` as props (instead of internal state) once TASK-041 is done; remove the UUID smoke-test form (or gate behind `NODE_ENV`). **Block: wait for TASK-041 Canvas refactor before this edit.**

#### Components Affected
- `InputDock` — HIGH (command parsing, scope tabs, loading state, focus mode are all new)
- `AppShell` — MEDIUM (spec state lifted here; prop changes to Canvas and InputDock)
- `Canvas` — LOW (only prop signature change: receives `specs` from AppShell instead of owning them)
- All 11 widgets — LOW (zero changes; they remain pure presenter components)
- `ActionCenter` — LOW (no changes)

#### API Changes
- New: `POST /orchestrate` — request: `{ query: string; scope: "all"|"clients"|"market"|"documents"|"analysis" }` · response: `{ specs: WidgetSpec[] }`. Defined by TASK-043; stubbed locally in TASK-042.

#### Database Changes
None.

### Local Slash-Command Stub (until TASK-043 lands)

The stub resolves the following commands client-side so the feature is demonstrable without the backend EP:

| Command | Stub response |
|---|---|
| `/client <name>` | `[{ component: "DnaCard", props: { clientId } }, { component: "HoldingsTable", props: { clientId } }]` |
| `/book` | `[{ component: "BookList", props: {} }]` |
| `/portfolio analysis` | `[{ component: "AllocationDonut" }, { component: "DriftBars" }, { component: "FitHeatmap" }]` |
| `/research` | `[{ component: "FallbackCard", props: { message: "Research task queued (TASK-043 pending)" } }]` |
| NL (no slash) | `POST /orchestrate` → on 404/network error → FallbackCard "Orchestrator not yet available" |

### Implementation Checklist
Based on CLAUDE.md principles:
- [ ] Reuse `InputDock.tsx` chrome as-is; extend, do not rewrite from scratch
- [ ] Reuse `apiPost()` from `api/client.ts` in the new `api/orchestrate.ts`
- [ ] Compose with TASK-041's registry and WidgetSpec types (import, don't re-define)
- [ ] Lift spec state to AppShell — mirrors existing `clientId` / `onClientChange` pattern
- [ ] Scope tabs: local UI state only — no backend involvement
- [ ] Hide-input focus mode: local boolean toggle; collapses the dock, Canvas takes full height
- [ ] Quick-command chips trigger the same `submit()` path — no special-casing
- [ ] Loading state on the send button (spinner / disabled) while orchestrator call is in-flight
- [ ] Follow SOLID principles — command parser is a single-responsibility pure function
- [ ] Write self-documenting code; no block comments
- [ ] No new packages required

### Risk Analysis
- **Risk Level:** MEDIUM
- **Main Risks:**
  - **TASK-041 sequencing**: Canvas's `WidgetSpec[]` state architecture (defined in TASK-041) must exist before AppShell can lift it. **Mitigation:** implement InputDock scope tabs + chips + hide-mode + parsing layer first (all independent of TASK-041); wire Canvas props last once TASK-041 is merged.
  - **TASK-043 not available**: Orchestrator EP doesn't exist yet. **Mitigation:** local stub covers all demo commands; NL shows graceful fallback. Swap stub for real call when TASK-043 lands with zero changes to InputDock logic.
  - **AppShell prop threading**: Adding `specs`/`onAddSpecs` to AppShell → Canvas → InputDock may cause re-render churn. **Mitigation:** `useCallback` for `onAddSpecs`; Canvas reads `specs` directly from AppShell state (no intermediate context needed at this scale).

### Estimated Effort
- **Original:** M
- **Adjusted:** M (unchanged)
- **Reason:** All chrome exists; the work is parsing + state wiring. The stub avoids backend dependency. Scope tabs + hide-mode are trivial local state. The only coordination cost is sequencing after TASK-041's Canvas refactor.
