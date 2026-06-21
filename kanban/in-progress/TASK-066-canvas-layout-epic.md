# TASK-066: Bento canvas + Chat/Fixed modes + collapsible rails [PARENT]

**Status:** IN-PROGRESS · **Epic:** EPIC-11 · **Priority:** P1 · **Type:** feature · **Effort:** L · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Rework the canvas shell so it uses screen space well and lets the RM control density. Two
**independent** axes (this distinction is load-bearing — don't recouple them):

1. **Arrangement — bento, always on.** The Canvas is always a tiled grid that fills the full
   width. Kills the wasted side gutters caused by today's `mx-auto max-w-3xl` column
   (`Canvas.tsx:51`). Applies in both modes.
2. **Overflow — Chat ↔ Fixed toggle.** The *only* thing the toggle changes:
   - **Chat:** the bento grid may grow taller than the viewport → **page scrolls**, newest tile
     appended + auto-scrolled to. A tiled transcript (today's feel, wider).
   - **Fixed:** the grid is **locked to the viewport** → no page scroll; density managed by
     **collapsing/closing tiles** (oldest non-pinned collapse first, overflow to a tray).

Shared chrome, identical in both modes: per-widget header controls (collapse / maximize / pin /
close), collapsible **left context rail** + **right ActionCenter rail** (hide-to-expand the
middle), and a per-widget `size` hint driving 1-col / 2-col / tall tiles.

## Business value
- Uses the full screen — wide widgets (before/after, portfolio) stop being crushed into 768px.
- RM controls their own density: scroll-everything (Chat) or fit-to-screen workbench (Fixed).
- Pin/hide rails give a focused middle on demand without losing context.

## Sub-tasks
- [ ] TASK-067: Bento grid engine + `size` hint in registry schema (frontend)
- [ ] TASK-068: Chat ↔ Fixed toggle + overflow policy + prefs persistence (frontend)
- [ ] TASK-069: Widget chrome — header controls (collapse / maximize / pin / close) (frontend)
- [ ] TASK-070: Collapsible side rails — left context rail + ActionCenter as right rail (frontend)

## Completion criteria
Canvas renders as a full-width bento in both modes; a header toggle switches Chat (scroll) ↔
Fixed (lock + collapse-to-fit), persisted per RM; every widget has collapse/maximize/pin/close;
both rails collapse to expand the centre. No backend changes.

## Existing resources to reuse
`Canvas.tsx` (becomes the grid engine) · `WidgetContainer.tsx` (header gains controls) ·
`AppShell.tsx` (grid rows, ActionCenter wiring) · `ActionCenter` (becomes right rail) ·
`PrefsProvider` (holds `defaultView`; add `layoutMode`) · `Header` (toggle host) ·
`registry/types.ts` (`WidgetSpec` gains optional `size`).

## Open decisions (carry into sub-tasks)
- Fixed-mode overflow policy: collapse oldest non-pinned → tray → scroll only as last resort. (TASK-068)
- Default mode: Chat (least surprising, matches today). (TASK-068)
- Pin target: left rail = client-context pins, right rail = ActionCenter (alerts/tasks). (TASK-069/070)
- `size` vocabulary: `"standard" | "wide" | "tall"` — finalise in TASK-067.

## Refs
frontend/src/components/shell/{AppShell,Canvas,Header,ActionCenter,InputDock}.tsx ·
frontend/src/components/widgets/WidgetContainer.tsx · frontend/src/registry/types.ts ·
frontend/src/prefs/PrefsProvider.tsx · docs/Requirements.md §UI

## Technical Analysis (Auto-generated 2026-06-20)

All referenced files were verified to exist; the ticket's Refs are accurate. This is a
**parent/epic coordination ticket** — the actual code changes land in TASK-067…070. No backend
changes (confirmed: nothing here touches FastAPI/data tools/registry contracts on the server).

### Existing Resources Found (verified)
- **`shell/Canvas.tsx`** — the render surface. **Line 51** confirms the gutter problem:
  `<div className="mx-auto max-w-3xl space-y-4">` (vertical stack). Empty state also uses
  `mx-auto max-w-3xl` (lines 24–25). Renders via `<WidgetRenderer key={i} spec={spec} />`
  (key = array index) and auto-scrolls on `specs` change (useEffect). → becomes the **bento grid
  engine** (TASK-067) + **overflow policy host** (TASK-068).
- **`shell/AppShell.tsx`** — outer grid `grid-rows-[auto_1fr_auto]` (Header / body / InputDock).
  Body grid `grid-rows-[1fr_auto] lg:grid-cols-[1fr_326px] lg:grid-rows-1` = Canvas + 326px
  ActionCenter right rail. Holds `actionCenterOpen` state + lifts `specs[]`. → gains left-rail
  column + `layoutMode` wiring (TASK-068/070).
- **`widgets/WidgetContainer.tsx`** — shared chrome wrapper. **Has a header** (title + optional
  `badges` + optional `source`) but **no controls**. Props: `title, source, children, className,
  badges`. → header gains collapse / maximize / pin / close (TASK-069).
- **`registry/types.ts`** — `WidgetSpec = { component: string; props: Record<string, unknown> }`.
  **No `size` field yet.** → add optional `size?: "standard" | "wide" | "tall"` (TASK-067).
- **`registry/{registry.ts,WidgetRenderer.tsx}`** — `Map<string, ComponentType>` (16 widgets) +
  `FallbackCard` for unknown components. Render protocol intact; `size` flows as a sibling of
  `props`, not into the component.
- **`prefs/PrefsProvider.tsx`** — `Prefs = { defaultView; density }`, persisted to LocalStorage
  key `waw-prefs`. → add `layoutMode: "chat" | "fixed"` (default `"chat"`); `PrefsPanel.tsx` can
  surface it but the primary control is the Header toggle (TASK-068).
- **`shell/ActionCenter.tsx`** — already a right `<aside>` rail (alerts + tasks), `open`-prop
  controlled, toggled by Header bell. → becomes the canonical **right rail** (TASK-070); minimal
  change.
- **`shell/Header.tsx`** — sticky top bar; already hosts the bell (ActionCenter toggle), gear
  (PrefsPanel), ThemeToggle. → hosts the **Chat ↔ Fixed** toggle (TASK-068).
- **`shell/CanvasActions.tsx`** — exists (untracked). Review before adding canvas-level controls
  to avoid duplication (TASK-069).

### Gaps / things that don't exist yet
- **No left context rail** — must be built net-new (TASK-070); add as a third AppShell grid
  column, mirror ActionCenter's collapsible `<aside>` pattern.
- **No widget header controls** — net-new in WidgetContainer (TASK-069).
- **No bento grid** — Canvas is a single `space-y-4` column today (TASK-067).
- **No per-widget `size`** and **no `layoutMode` pref** — both net-new schema additions.

### Impact Assessment
| File | Sub-task | Impact |
|------|----------|--------|
| `registry/types.ts` (`WidgetSpec`) | 067 | LOW — additive optional field, backwards-compatible |
| `shell/Canvas.tsx` | 067/068 | HIGH — core layout rewrite (grid engine + overflow modes) |
| `widgets/WidgetContainer.tsx` | 069 | MEDIUM — header gains controls; consumed by all 16 widgets |
| `shell/AppShell.tsx` | 068/070 | HIGH — grid columns + layoutMode + left-rail wiring |
| `prefs/PrefsProvider.tsx` / `PrefsPanel.tsx` | 068 | LOW — additive pref + persistence |
| `shell/Header.tsx` | 068 | LOW — one toggle control |
| `shell/ActionCenter.tsx` | 070 | LOW — relabel/wire as right rail |
| new left-rail component | 070 | NEW |

### Implementation order (dependency-aware)
1. **TASK-067** first — `size` schema + bento engine is the foundation everything tiles into.
2. **TASK-069** — widget chrome controls (needed before Fixed-mode collapse-to-fit works).
3. **TASK-068** — Chat ↔ Fixed toggle + overflow policy + prefs (depends on 067 grid + 069
   collapse).
4. **TASK-070** — collapsible rails (independent of overflow; can parallel 068).

### Risk Analysis
- **Risk Level:** MEDIUM.
- **Recoupling the two axes** (arrangement vs overflow) — the ticket flags this as load-bearing.
  Mitigation: `size` (per-widget) and `layoutMode` (global) must stay orthogonal; bento applies
  in both modes, toggle only changes overflow handling. Enforce in TASK-067/068 review.
- **All-16-widgets blast radius** from WidgetContainer header change. Mitigation: keep controls
  additive/optional; default render unchanged when handlers absent.
- **Index-keyed widgets** (`key={i}`) — pin/close/reorder will need stable IDs. Mitigation: flag
  for TASK-069 (introduce a stable per-tile id) rather than relying on array index.
- **Auto-scroll behaviour** in Canvas only makes sense in Chat mode. Mitigation: gate the
  scroll-into-view effect on `layoutMode === "chat"` (TASK-068).

### Estimated Effort
- Original: **L** (epic spanning 4 sub-tasks). **Unchanged** — analysis confirms scope; no
  backend work, all changes are in the verified frontend shell/registry/prefs surface.
