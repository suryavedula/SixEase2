# TASK-068: Chat ↔ Fixed toggle + overflow policy + prefs persistence

**Status:** IN-PROGRESS · **Epic:** EPIC-11 · **Parent:** TASK-066 · **Priority:** P1 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Add the **scroll-behaviour toggle** layered on top of the always-on bento grid (TASK-067). This is
the *only* axis the toggle controls — arrangement stays bento either way.

- **Chat mode:** bento grid may exceed viewport height → **page scrolls**; newest tile appended and
  auto-scrolled into view (restore the `Canvas.tsx:19` behaviour for this mode only).
- **Fixed mode:** Canvas height **locked to the viewport** (`overflow-hidden`); no page scroll.
  Density managed by collapse/close. **Overflow policy:** when tiles can't fit, **collapse oldest
  non-pinned tiles to title-bar first**, then stash further overflow in a "+N more" tray; page
  scroll only as an explicit last resort.
- **Toggle UI:** segmented control in `Header` (💬 Chat / ▦ Fixed), beside the ActionCenter toggle.
- **Persist** as `layoutMode` in `PrefsProvider` (sits next to `defaultView`) so it survives reload.
  Default **Chat**.

## Acceptance Criteria
- [x] Header segmented toggle switches Chat ↔ Fixed; reflects current mode
- [x] Chat mode: page scrolls, newest tile auto-scrolled into view
- [x] Fixed mode: no page scroll; tiles collapse-oldest-first, then tray, before any scroll
- [x] `layoutMode` persisted in prefs; restored on reload; defaults to Chat
- [x] Switching modes re-lays-out the *same* widgets with **no refetch**
- [x] Pinned/maximized tiles (TASK-069) respected by the overflow policy
- [x] Loading/empty states correct in both modes

## Implementation Note (2026-06-20)
Toggle, prefs/persistence, both render modes, and collapse-oldest were already in the tree from the
TASK-066 epic. This change added the remaining **overflow tray** in `Canvas.tsx`:
- **Monotonic density pipeline** in the Fixed-mode reflow: tier 1 collapses the oldest non-pinned
  tile → tier 2 stashes the oldest (already-collapsed) tile into a **"+N more" tray** → tier 3 falls
  through to the container's `overflow-auto` as the explicit last-resort scroll. Collapse/tray only
  ever *reduce*, so the `ResizeObserver` can't oscillate.
- **Loop-free restore:** a local `keptIds` set marks RM-restored tiles so the pipeline never
  re-stashes them. Per-tile chip restore + "Restore all" (which opens everything → last-resort
  scroll). Tray state is local/ephemeral (`trayedIds`/`keptIds`) — `specs[]` stays the single
  source of truth; pruned to live tiles on close/clear.
- Fixed mode switched from `overflow-hidden` to `overflow-auto` so the last-resort scroll replaces
  the previous silent clipping (honours the "no fallbacks" rule).
- Reconciled with TASK-067's concurrent container-query grid + insert-highlight (`isNew`) in the same
  file; `tsc -b --noEmit` and `vite build` both pass.

## Technical Approach
### Reuse
`PrefsProvider` (add `layoutMode: "chat" | "fixed"`), `Header`, `Canvas` (branch on mode),
collapse state from TASK-069.
### New
Mode branch in `Canvas` (scroll vs lock+collapse), overflow/collapse-oldest logic, "+N more" tray,
header segmented control.

## Dependencies
TASK-067 (grid engine) · TASK-069 (collapse state for the overflow policy)

## Refs
frontend/src/prefs/PrefsProvider.tsx · frontend/src/components/shell/{Header,Canvas}.tsx ·
docs/Requirements.md §UI

---

## Technical Analysis (Auto-generated 2026-06-20)

> ⚠️ **The ticket's premise is mostly stale** (same pattern as TASK-067). It was written as if
> Chat↔Fixed did not yet exist. In the meantime the in-flight **TASK-066 epic** (in-progress,
> uncommitted in the working tree) already shipped the toggle, the prefs key, both render modes,
> and the Fixed-mode auto-collapse policy. **6 of 7 AC are effectively met today.** The one real
> remaining piece is the **"+N more" overflow tray** and the page-scroll-as-last-resort escape
> hatch. Read the gap analysis before writing code — most of this is verify-and-finish, not build.

### Existing Resources Found (already in the working tree)
- **`prefs/PrefsProvider.tsx`** — `LayoutMode = "chat" | "fixed"` type, the `layoutMode` field in
  `Prefs`/`DEFAULT_PREFS` (default **`"chat"`**), localStorage persistence (`waw-prefs`), and a
  validating re-hydrate in `readInitialPrefs()` (lines 52–55) **already exist**. **AC #4 is done.**
- **`shell/Header.tsx`** — the segmented Chat (💬 `MessageSquare`) / Fixed (▦ `LayoutGrid`)
  control **already exists** (lines 60–82), `aria-pressed`-wired, sitting beside the Action
  Center bell, writing `setPref("layoutMode", …)`. **AC #1 is done.**
- **`shell/Canvas.tsx`** — already takes `layoutMode` as a prop and branches on it:
  - **Chat:** `overflow-auto` + `scrollIntoView` on `bottomRef` as `specs.length` grows
    (lines 54–59, 156). **AC #2 is done.**
  - **Fixed:** `overflow-hidden` (line 129) + a `useLayoutEffect` reflow (lines 64–81) that, via a
    `ResizeObserver`, collapses the **oldest non-pinned, non-bare** tile (`!t.rail && !t.collapsed
    && !BARE.has(...)`) while `scrollHeight > clientHeight`. Collapse-only, never auto-expand, to
    avoid oscillation; skipped while a tile is maximized. **AC #3 first half (collapse-oldest) is
    done; the tray + last-resort scroll are NOT.**
- **`shell/AppShell.tsx`** — owns `specs[]`; passes `layoutMode={prefs.layoutMode}` to `Canvas`
  and supplies `onAutoCollapse={handleSetCollapsed}` (set, not toggle). **Mode is a prop over the
  same `specs[]` state ⇒ switching modes re-lays-out with zero refetch. AC #5 is done.**
- **`shell/CanvasTile.tsx`** — collapse/maximize/pin/close chrome (TASK-069 functionality already
  in-tree despite TASK-069 still showing BACKLOG). The Fixed reflow keys off `tile.collapsed` /
  `tile.rail` from this model. Maximized tiles freeze the reflow; pinned (`rail`) tiles are
  excluded from collapse victims. **AC #6 is done.**

### Gap Analysis — what this ticket still actually has to do
1. **No "+N more" tray (the core remaining feature).** Today Fixed mode is `overflow-hidden`
   (`Canvas.tsx:129`) and only collapses oldest tiles to a 40px title strip. Once every
   non-pinned tile is collapsed and the strips *still* don't fit, the grid is simply **clipped** —
   content is silently lost with no affordance to reach it (violates AC #3's "then stash further
   overflow in a '+N more' tray" and the "no fallbacks" project rule — clipping is a silent drop).
   Need: after the collapse pass is exhausted, **stash the oldest overflowing tiles into a "+N
   more" tray** (a chip/popover at the canvas edge) rather than clipping them.
2. **No explicit page-scroll last resort.** AC #3 wants "page scroll only as an explicit last
   resort." Current Fixed mode never scrolls (it clips). Decide the escape hatch: once even the
   tray is impractical (or as the simplest acceptable degradation), allow the canvas inner div to
   scroll — but only as the final tier, after collapse + tray.
3. **AC #7 (loading/empty states in both modes) — verify only.** The empty state
   (`Canvas.tsx:83–108`) and "clear canvas" are mode-independent and look correct in both; just
   confirm no Fixed-mode-specific regression (e.g. the reflow effect no-ops cleanly at
   `specs.length === 0`, which it does — early return on `specs.length === 0` short-circuits before
   the grid renders).

**Design decision to make first (don't silently pick):** where the tray lives and what "stash"
means for tile state. Two viable shapes —
- **(a) Derived/ephemeral tray:** Canvas computes, after the collapse pass still overflows, how
  many trailing tiles to hide and renders them as a "+N more" chip that pops them back on click
  (local Canvas state, no `specs[]` mutation). Cheapest; keeps `specs[]` the single source of
  truth; survives mode switches cleanly. **Recommended.**
- **(b) Persisted `trayed` flag** on `CanvasTileSpec` (next to `collapsed`/`rail`), mutated in
  `AppShell` like the others. More uniform with the existing chrome model but adds another state
  axis and another reflow interaction. Heavier; only worth it if the tray must survive reload.
Recommend **(a)** unless the tray must persist — `specs[]` aren't persisted anyway, so (b) buys
little. Coordinate with TASK-070 (rails, in-progress): trayed tiles must be mutually exclusive
with pinned (`rail`) tiles, and the tray must not eat pinned/maximized tiles.

### Dependencies Required
- Frontend packages: none new. lucide already present for a tray icon; Tailwind JIT — enumerate
  any dynamic classes as static strings (same caveat as `railCols`).
- Backend / DB / Docker: none. Pure frontend, render-only (no API or `{component, props}` contract
  change — grounding rule intact).

### Impact Assessment
#### Files to Modify
- `frontend/src/components/shell/Canvas.tsx`: extend the Fixed-mode reflow to, after the collapse
  pass is exhausted, move oldest overflow into a "+N more" tray; add the tray UI + last-resort
  scroll tier. (No change needed for Chat mode — already correct.)
- `frontend/src/prefs/PrefsProvider.tsx`: **no change** — `layoutMode` already complete.
- `frontend/src/components/shell/Header.tsx`: **no change** — toggle already complete.
- *(only if option (b))* `frontend/src/registry/types.ts` + `frontend/src/components/shell/AppShell.tsx`:
  add a `trayed` flag + handler. Avoid if (a) is chosen.

#### Components Affected
- `Canvas` — **MEDIUM** (new tray tier + scroll fallback layered onto the existing reflow effect;
  must not reintroduce oscillation — keep the collapse→tray→scroll ordering monotonic).
- `CanvasTile` — **LOW** (unchanged if tray is derived; only touched under option (b)).
- `AppShell` — **LOW** (unchanged under option (a)).
- TASK-070 (rails) — **LOW–MEDIUM**: tray and rails both remove tiles from the main grid flow;
  ensure a pinned tile is never also trayed, and unpin restores correctly.

#### API / Database Changes
- None. Render-only; `{component, props, size?}` contract unchanged.

### Implementation Checklist
- [ ] Do **not** re-add `layoutMode`, the Header toggle, the Chat auto-scroll, or the Fixed
      collapse pass — all present. This ticket = tray + last-resort scroll + verify.
- [ ] After the collapse pass still overflows, stash oldest non-pinned tiles into a **"+N more"**
      tray instead of clipping (no silent drop — honours the "no fallbacks" rule).
- [ ] Add page-scroll as the **explicit last tier** only, after collapse + tray.
- [ ] Keep collapse→tray→scroll ordering monotonic (collapse-only, never auto-expand) so the
      `ResizeObserver` can't oscillate.
- [ ] Respect pinned (`rail`) and maximized tiles — never tray or scroll them out of reach.
- [ ] Verify empty/loading + clear-canvas behave in both modes; verify mode switch still does no
      refetch (it won't — mode is a prop over `specs[]`).
- [ ] Light/dark tokens intact; no console errors; keyboard-reachable tray control.

### Risk Analysis
- **Risk Level**: LOW–MEDIUM
- **Main Risks**:
  - *Reflow oscillation* once a tray/scroll tier feeds back into `ResizeObserver` → mitigate by
    keeping the density pipeline strictly monotonic (collapse → tray → scroll, never reverse
    inside the observer) and by deriving the tray from already-collapsed state.
  - *Silently clipping content* (current behaviour) if the tray is skipped → the whole point of
    this ticket; treat any clip path as a bug.
  - *Conflict with in-flight TASK-066/070 edits to `Canvas.tsx`* (uncommitted tree) → land as part
    of the same epic branch; sync before editing.
- **Worth a quick design check with the user/TASK-066 owner:** option (a) vs (b) for tray state,
  and whether last-resort scroll is even desirable vs. "tray is the floor."

### Estimated Effort
- Original: **M**
- Adjusted: **S** — toggle, prefs, persistence, both render modes, and collapse-oldest are already
  in the tree (6/7 AC). Remaining work is one feature (the "+N more" tray + scroll tier) plus
  verification.
- Reason: ticket assumed greenfield; the TASK-066 epic already implemented the bulk.
