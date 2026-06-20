# TASK-044: RM view preferences and default view

**Status:** IN-PROGRESS · **Epic:** EPIC-10 · **Priority:** P1 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Let the RM set presentation preferences (chart vs table, dense vs narrative, default entry view, theme); the same data renders to preference; persist per RM.

## Acceptance Criteria
- [ ] default entry view configurable
- [ ] preference selects default widget variant (V2)
- [ ] persisted across sessions

## Dependencies
TASK-041 (in-progress — registry + WidgetSpec type needed for variant wiring), TASK-003 ✅ (done — ThemeProvider/ThemeToggle pattern to follow)

## Refs
Requirements §17 UI-3/UI-7

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **`ThemeProvider.tsx`** (`frontend/src/theme/ThemeProvider.tsx`): canonical localStorage pattern for persisted UI state. Exports `useTheme()` hook + `ThemeProvider` wrapper. Stores `waw-theme` key. **Mirror this pattern exactly** for prefs — `waw-prefs` key, same structure.
- **`ThemeToggle.tsx`** (`frontend/src/components/shell/ThemeToggle.tsx`): a concrete settings control to reuse inside the PrefsPanel (so theme is one preference among several, all in one place).
- **`App.tsx`**: wraps everything in `<ThemeProvider>`. Add `<PrefsProvider>` at the same level.
- **`Canvas.tsx`** (`frontend/src/components/shell/Canvas.tsx`): the consumer of `defaultView` pref — when a clientId becomes active, the initial widget list is derived from the pref. Comment already says *"The widget registry + command-driven render arrive in TASK-041"* — `defaultView` slots naturally into that spec-driven path.
- **`Header.tsx`** (`frontend/src/components/shell/Header.tsx`): the right side already has ThemeToggle + avatar + bell buttons. Add a ⚙️ gear button here to open the PrefsPanel.
- **Widget registry (TASK-041, in-progress)**: will introduce `WidgetSpec { component, props }`. The `widgetVariant` pref (chart vs table) controls which component name fills a slot in the default spec list. Variant wiring completes once TASK-041 ships; the pref store and UI land now.

### Dependencies Required
- **Frontend packages:** None — pure localStorage, no new packages.
- **Backend packages:** None — no backend changes.
- **Database migrations:** None — no RM identity/auth exists; localStorage is the right scope.
- **Docker services:** None.

### Impact Assessment

#### Files to Create
- `frontend/src/prefs/PrefsProvider.tsx` — `Prefs` type + `PrefsProvider` + `usePrefs()` hook; stores `waw-prefs` in localStorage; same pattern as `ThemeProvider`
- `frontend/src/prefs/PrefsPanel.tsx` — slide-down or popover settings panel; shows `defaultView` radio, `density` toggle, and a `<ThemeToggle />` row; opened from the Header gear button

#### Files to Modify
- `frontend/src/App.tsx` — add `<PrefsProvider>` wrapping (alongside `ThemeProvider`)
- `frontend/src/components/shell/Header.tsx` — add ⚙️ gear button + `PrefsPanel` rendered conditionally
- `frontend/src/components/shell/Canvas.tsx` — consume `usePrefs().defaultView` to seed the initial widget spec when clientId first becomes non-null; no change to the UUID smoke-test path

#### Components Affected
- `ThemeProvider` — LOW (not modified; only reused inside PrefsPanel)
- `Canvas` — LOW (reads one new value from prefs; external interface unchanged)
- `Header` — LOW (one new button added; layout unchanged)
- `AppShell` — LOW (no changes; PrefsProvider added at App level)
- All widgets — NONE (zero changes; variant selection wired in TASK-041)

#### API Changes
None.

#### Database Changes
None.

### Prefs Shape
```typescript
export type DefaultView = "holdings" | "dna" | "portfolio" | "alerts";
export type WidgetDensity = "dense" | "narrative";

export interface Prefs {
  defaultView: DefaultView;   // first widget shown when a client opens
  density: WidgetDensity;     // dense = compact data table feel; narrative = label-rich
}

const DEFAULT_PREFS: Prefs = { defaultView: "holdings", density: "narrative" };
const STORAGE_KEY = "waw-prefs";
```

Theme is intentionally **not** part of `Prefs` — it lives in `waw-theme` via `ThemeProvider`. PrefsPanel surfaces a `<ThemeToggle />` row so all display settings are in one place, but storage stays separate.

### Implementation Checklist
Based on CLAUDE.md principles:
- [ ] Follow `ThemeProvider` pattern exactly — same hook shape, same `readInitialValue` guard, same `useEffect`/`useCallback`/`useMemo` structure
- [ ] Reuse `<ThemeToggle />` inside `PrefsPanel` — do not re-implement theme switching
- [ ] `defaultView` → `Canvas` consumes it to seed initial widget specs; do NOT hardcode widget stacks anywhere else
- [ ] `density` pref: store it now; widget consumption wired when TASK-041 registry is shipped (widgets get a `density` prop)
- [ ] `widgetVariant` (chart vs table) is the V2 AC item — depends on TASK-041 `WidgetSpec`; placeholder pref key added to the shape but wiring deferred to TASK-041 merge
- [ ] Follow SOLID principles — `PrefsProvider` single responsibility: read/write prefs; `PrefsPanel` single responsibility: present controls
- [ ] No loading states needed (synchronous localStorage read on mount)
- [ ] Self-documenting code; no prose comments beyond task-reference lines

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - TASK-041 not yet merged: `widgetVariant` pref cannot be wired to widget rendering until the registry's `WidgetSpec` is available. **Mitigation:** pref key is stored and exposed via `usePrefs()` now; Canvas reads it when constructing the spec list once TASK-041 lands.
  - PrefsPanel UX positioning: placing an open/close toggle in the Header adds state that needs to live somewhere. **Mitigation:** hold `panelOpen` state locally in `Header` (not lifted to AppShell) — it's view-only, no data flow to sibling components.

### Estimated Effort
- **Original:** S
- **Adjusted:** S (unchanged)
- **Reason:** Pure frontend, no backend, 2 new files + 3 small edits. Pattern is already established by `ThemeProvider`.
