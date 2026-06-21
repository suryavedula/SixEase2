# TASK-069: Widget chrome — collapse / maximize / pin / close controls

**Status:** BACKLOG · **Epic:** EPIC-11 · **Parent:** TASK-066 · **Priority:** P1 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20

## Description
Give every tile a header control cluster — the mechanism that makes "manage density without
scrolling" work, and the source of pin/collapse state the other sub-tasks consume.
`WidgetContainer` header today is title + source badge only (`WidgetContainer.tsx:26`); add:

- **▾ Collapse** → title-bar only; click to re-expand. (Primary lever for Fixed-mode overflow.)
- **⤢ Maximize** → focus mode: this tile fills the canvas; restore returns it to the grid.
- **📌 Pin** → send the tile to a rail (TASK-070). Default target: **left rail** for client-context
  tiles, **right rail (ActionCenter)** for alerts/tasks.
- **× Close** → remove the tile (calls back into `AppShell` specs state).

State lifted so `Canvas`/overflow policy (TASK-068) and rails (TASK-070) can read it: per-tile
`{ collapsed, maximized, pinned, pinnedRail }`. Controls work identically in Chat and Fixed.

## Acceptance Criteria
- [ ] `WidgetContainer` header shows collapse / maximize / pin / close, theme-tokenised
- [ ] Collapse toggles to title-bar-only and back; state persists while the tile lives
- [ ] Maximize fills the canvas; restore returns to prior grid position/size
- [ ] Close removes the tile from `specs[]` (state owned by `AppShell`)
- [ ] Pin hands the tile to the correct rail (left/right per type) — wired with TASK-070
- [ ] Controls reachable in both Chat and Fixed; keyboard-focusable; no console errors

## Technical Approach
### Reuse
`WidgetContainer.tsx`, `AppShell` specs state + `handleClearSpecs`/append patterns, lucide icons,
`CanvasActions` context.
### New
Header control cluster, per-tile UI-state model (collapsed/maximized/pinned), close→specs removal,
maximize overlay.

## Dependencies
TASK-067 (grid context) · TASK-070 (pin destination). Provides collapse state to TASK-068.

## Refs
frontend/src/components/widgets/WidgetContainer.tsx · frontend/src/components/shell/{AppShell,CanvasActions}.tsx
