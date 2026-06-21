# TASK-070: Collapsible side rails — left context rail + ActionCenter as right rail

**Status:** IN-PROGRESS · **Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20 · **Epic:** EPIC-11 · **Parent:** TASK-066 · **Priority:** P1 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20

## Description
Generalise the docked-panel idea into **two collapsible rails** that flank the bento canvas, so the
RM can hide them to expand the middle ("pin to corner, hide to expand the centre").

- **Right rail = ActionCenter** (already a fixed 326px column, `AppShell.tsx:181`) — now collapses
  to a **thin strip** of icons + counts (alerts/tasks badges); click/hover to re-expand.
- **Left rail = new context rail** — holds tiles pinned via TASK-069 (e.g. active client's
  Client360, a watchlist) as compact cards. Collapsible to a thin strip too.
- Either rail collapsed → **centre bento expands** to reclaim the width; both collapsed → full-width
  canvas. Rail open/closed state persisted in `PrefsProvider` alongside `layoutMode`.
- Pin routing: client-context tiles → left rail; alert/task tiles → right rail (ActionCenter).

## Acceptance Criteria
- [ ] ActionCenter becomes the right rail; collapses to a thin icon+count strip and re-expands
- [ ] New left context rail renders pinned tiles as compact cards; collapsible
- [ ] Collapsing either rail expands the centre bento; both collapsed = full-width canvas
- [ ] Pinning a tile (TASK-069) routes it to the correct rail by type
- [ ] Rail open/closed state persisted in prefs; restored on reload
- [ ] Works in both Chat and Fixed; responsive (rails stack/hide on narrow viewports)

## Technical Approach
### Reuse
`AppShell.tsx` body grid (`grid-cols-[1fr_326px]`), `ActionCenter`, `WidgetContainer` (compact
variant for rail cards), `PrefsProvider`, pin state from TASK-069.
### New
Left-rail component + container, collapse strips for both rails, AppShell grid that adapts column
template to rail open/closed, pin→rail routing.

## Dependencies
TASK-069 (pin action + state) · TASK-067 (canvas width to expand into)

## Refs
frontend/src/components/shell/{AppShell,ActionCenter}.tsx ·
frontend/src/components/widgets/WidgetContainer.tsx · frontend/src/prefs/PrefsProvider.tsx

---

## Technical Analysis (Auto-generated 2026-06-20)

> **Key finding:** much of this ticket is already scaffolded by TASK-066/069. Both rails
> exist, the centre bento already expands when a rail closes, and pinned tiles already dock
> in the left rail. The genuine remaining scope is **3 things**: collapse-to-strip, prefs
> persistence, and pin→rail *routing by type*. Don't rebuild the rails — extend them.

### Existing Resources Found
- **Components:** `ContextRail.tsx` (left rail, renders current client + pinned tiles as
  compact cards, has a collapse button), `ActionCenter.tsx` (right rail, `<aside>` with
  category chips + alert/task lists), `Canvas.tsx`, `CanvasTile.tsx` (per-tile chrome incl.
  pin/collapse), `Header.tsx` (already has both rail toggles wired).
- **State (AppShell.tsx):** `actionCenterOpen` / `contextRailOpen` (`useState`), `pinnedTiles
  = specs.filter(t => t.pinned)`, `handleTogglePin`, `lastClientId`/`currentClient` derivation.
- **Grid:** `railCols` (lines 211–218) and `railRows` (219–221) already drop a rail's column
  when closed → centre reclaims width. Both-closed → `lg:grid-cols-1` (full-width). ✅
- **Prefs:** `PrefsProvider` persists the whole `prefs` object to `localStorage` (`waw-prefs`)
  with per-field validation in `readInitialPrefs`; `setPref(key, value)` already exists.
- **Types:** `CanvasTileSpec` carries `pinned?` / `collapsed?` flags (TASK-069).
- **Registry:** 17 widgets in `registry.ts` — all are client-context views (Client360,
  PortfolioView, Research, EmailDraft, MeetingPrep, DnaCard…). See routing note below.

### Dependencies
- TASK-069 (pin action + `pinned` flag) — **code present** in CanvasTile/AppShell (ticket
  header still says BACKLOG; status tracking lags the code).
- TASK-067 (bento grid width to expand into) — **code present** (`railCols`).
- No new npm packages. Icons via `lucide-react` (`PanelLeft`, `PanelLeftClose`, `PinOff`
  already imported; add `PanelRightClose`/`Bell`/`ListChecks` as needed).

### Gap Analysis (acceptance criteria → state)
| # | Criterion | State | Work |
|---|-----------|-------|------|
| 1 | ActionCenter = right rail, collapses to **thin icon+count strip**, re-expands | ⚠️ Partial — it IS the right rail but `if (!open) return null` makes it vanish; re-expand only via header bell | **Build strip** |
| 2 | Left context rail renders pinned tiles as compact cards; collapsible to strip | ⚠️ Partial — renders/collapses, but to `null`, no strip | **Build strip** |
| 3 | Collapsing either rail expands centre; both = full-width | ✅ Done (`railCols`) | grid update for strip width |
| 4 | Pin routes tile to correct rail **by type** | ❌ All pinned tiles → left rail; no type routing; ActionCenter takes no tiles | **Classifier + routing** |
| 5 | Rail open/closed persisted in prefs; restored on reload | ❌ `useState` in AppShell, not in `Prefs` | **Move to PrefsProvider** |
| 6 | Works in Chat + Fixed; responsive (rails hide on narrow) | ✅ Rails are `lg:`-only, `railRows` stacks AC on mobile | spot-check |

### Files to Modify
- `frontend/src/prefs/PrefsProvider.tsx` — add `contextRailOpen: boolean` + `actionCenterOpen:
  boolean` to `Prefs`, `DEFAULT_PREFS`, and `readInitialPrefs` validation. (Persistence is free.)
- `frontend/src/components/shell/AppShell.tsx` — drop the two `useState`s, read/write rail
  state via `prefs`/`setPref`; replace `pinnedTiles` with a **type-split** (left vs right);
  pass right-rail pinned tiles into ActionCenter; update `railCols` so a *collapsed* rail
  renders a narrow strip column (e.g. `48px`) instead of `0`.
- `frontend/src/components/shell/ActionCenter.tsx` — replace `if (!open) return null` with a
  collapsed **strip** branch (vertical icons + alert/task count badges; click → expand).
  Accept + render any pinned tiles routed here.
- `frontend/src/components/shell/ContextRail.tsx` — same collapse-to-strip treatment (client
  initial + pinned count); click strip → re-open.
- `frontend/src/components/shell/Header.tsx` — toggles already exist; verify they flip the
  prefs-backed state (bell currently toggles AC, `PanelLeft` toggles context rail).

### Design decision needed — pin→rail routing (AC #4)
The ticket says "client-context tiles → left, alert/task tiles → right," but **every widget in
the registry is a client-context view** — there are no "alert/task" *tiles* (alerts/tasks are
separate data inside ActionCenter, not `CanvasTileSpec`s). Recommended resolution: define a
small `RAIL_BY_COMPONENT` map (or a `rail?: "left" | "right"` hint on the spec) and default
unmapped components to the **left** rail. Candidates for the right rail: `Research`,
`EmailDraft`, `MeetingPrep` (action-oriented drafts) — confirm with design before coding.

### Implementation Checklist
- [ ] Extend `Prefs` with `contextRailOpen` + `actionCenterOpen`; validate in `readInitialPrefs`
- [ ] Migrate AppShell rail state off `useState` onto prefs (`setPref`)
- [ ] ActionCenter: collapsed strip (icons + alert/task counts), click to expand
- [ ] ContextRail: collapsed strip (client initial + pinned count), click to expand
- [ ] `railCols`: collapsed rail = narrow strip column, not dropped; both open/closed cases
- [ ] Pin routing: `RAIL_BY_COMPONENT` split; feed right-rail tiles into ActionCenter
- [ ] Verify Chat + Fixed; narrow-viewport (rails hidden/stacked) still works
- [ ] Reuse `WidgetContainer` compact variant for rail cards (don't author new card chrome)

### Risk Analysis
- **Risk Level:** LOW–MEDIUM.
- Prefs shape change: existing `waw-prefs` in localStorage lacks the new keys →
  `readInitialPrefs` must fall back to defaults (it validates per-field, so safe if done right).
- Strip-vs-dropped grid math: the both-collapsed "full-width" case (AC #3) must still hold once
  collapsed rails become narrow strips — don't regress the `lg:grid-cols-1` path.
- Routing ambiguity (above) is the only true unknown; everything else is mechanical.

### Estimated Effort
- Original: **M**. Adjusted: **S–M** — the rails, grid-expand, and pin-dock already exist;
  remaining work is strips + prefs migration + a routing map.
