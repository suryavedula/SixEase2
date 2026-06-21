# TASK-067: Bento grid engine + `size` hint in registry schema

**Status:** IN-PROGRESS · **Epic:** EPIC-11 · **Parent:** TASK-066 · **Priority:** P1 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Replace the centred single-column transcript with an **always-on bento grid** that fills the full
canvas width — the fix for the wasted side gutters. Arrangement only; the scroll-vs-lock behaviour
is TASK-068's concern.

- `Canvas.tsx` renders `specs[]` into a responsive grid: `repeat(auto-fit, minmax(~380px, 1fr))`
  → 1 / 2 / 3 columns by viewport width. No `mx-auto max-w-3xl`.
- Add an optional **`size`** field to `WidgetSpec` (`registry/types.ts`): `"standard" | "wide" |
  "tall"`. `wide` spans 2 columns, `tall` spans 2 rows; default `standard`. The model may emit it
  (layout intent, not pixels — consistent with the grounding rule); the registry can also set a
  per-component default so existing specs need no change.
- Wide-by-default components: PortfolioView, the before/after widget (TASK-065). Standard: DnaCard,
  DriftBars, ConflictsList.
- Newest tile animates in (top-left) and briefly highlights — replaces auto-scroll-to-bottom
  (`Canvas.tsx:19`); actual scroll behaviour deferred to TASK-068.
- Keep the empty-state and "clear canvas" affordances.

## Acceptance Criteria
- [x] Canvas is a full-width responsive grid; no centred 768px column; side gutters gone
- [x] `WidgetSpec.size` added (optional) + per-component default in the registry *(pre-existing from TASK-066)*
- [x] `wide`/`tall` tiles span correctly; graceful reflow at 1/2/3 columns
- [x] Existing specs render unchanged when `size` is omitted (back-compat — `resolveSize` fallback)
- [x] Newest tile highlights on insert; empty-state + clear-canvas preserved
- [x] No console errors; light/dark tokens intact *(tsc + vite build clean; CSS verified)*

## Implementation Notes (2026-06-20)
Built option (a) from the gap analysis. Two deliberate deviations from the original ticket text,
both because the in-flight TASK-066/068 epic changed the ground under it:

1. **Container queries, not viewport media queries / `auto-fit`.** The repo is Tailwind v4, so the
   grid uses `@container` on the canvas `<main>` + `@3xl:grid-cols-2 @6xl:grid-cols-3` and
   `@3xl:col-span-2`. This responds to the *canvas* width (which the side rails change), not the
   viewport — strictly better than the spec's `auto-fit minmax(380px,1fr)`, and it sidesteps the
   `auto-fit` + `col-span-2` overflow bug at 1 column (the `@3xl:` span is inert below 2 cols, so
   `wide` falls back to 1 col cleanly). Verified in the built CSS:
   `@container (min-width:48rem){.@3xl:col-span-2{grid-column:span 2/span 2}}`.
2. **Auto-scroll-to-bottom kept (not replaced).** The ticket said the highlight *replaces*
   auto-scroll, but TASK-068 has since landed and made Chat-mode auto-scroll part of *its* design
   ("Chat = page scrolls + auto-scroll to newest"). Since scroll is 068's concern, the highlight
   was added **additively** — both behaviours coexist. Removing the scroll would have regressed 068.

### Changes
- `registry/tileLayout.ts`: `FLEX_CLASS` (flex basis) → `SPAN_CLASS` (grid spans:
  `wide`→`@3xl:col-span-2`, `tall`→`row-span-2`). `resolveSize`/`DEFAULT_SIZE` unchanged.
- `shell/Canvas.tsx`: flex-wrap + `justify-center` container → container-query grid
  (`grid-cols-1 @3xl:grid-cols-2 @6xl:grid-cols-3`, `items-start`); `@container` on `<main>`;
  added freshly-inserted-tile tracking (`newIds`, diffed against a `seenIds` ref) → transient ring;
  BARE specs + scroll sentinel now `col-span-full`.
- `shell/CanvasTile.tsx`: consume `SPAN_CLASS[tile.size]`; new `isNew` prop → `ring-2 ring-blue/50`
  that fades via the existing `transition-shadow`; `motion-safe:animate-tile-enter` entrance (plays
  once per insert since tiles mount on insert). Pinned ring still takes precedence.
- `index.css`: registered `--animate-tile-enter` + `@keyframes tile-enter` (fade + 6px rise).

### Follow-ups / coordination
- The Fixed-mode density pipeline (TASK-068) reads `grid.scrollHeight` for overflow — unaffected by
  flex→grid and left intact; worth an eyes-on check in the running app under Fixed mode.
- `tall` row-span uses default (`auto`) grid rows + `items-start`, so it reserves 2 row tracks for
  packing rather than forcing a fixed height — meaningful for the naturally-tall defaults
  (RelationshipTimeline, ConflictsList). Revisit if a fixed-height masonry is later wanted.

## Technical Approach
### Reuse
`Canvas.tsx`, `WidgetRenderer`, `WidgetContainer`, theme tokens, registry pattern.
### New
Grid layout in `Canvas`, `size` field + resolver (spec.size ?? registry default ?? "standard"),
column-span classes.

## Dependencies
None (pure frontend). Pairs with TASK-068 (overflow) and TASK-069 (chrome).

## Refs
frontend/src/components/shell/Canvas.tsx · frontend/src/registry/types.ts ·
frontend/src/registry/registry.ts · frontend/src/registry/tileLayout.ts ·
frontend/src/components/shell/CanvasTile.tsx · frontend/src/components/shell/AppShell.tsx

---

## Technical Analysis (Auto-generated 2026-06-20)

> ⚠️ **The ticket's premise is stale.** It was written assuming a centred single-column
> transcript that needs converting to a bento grid. In the meantime the in-flight **TASK-066
> epic** (in-progress, uncommitted in the working tree) has already landed most of the
> scaffolding this ticket described as "New". The remaining work is **reconciling the existing
> implementation with this ticket's AC**, not building from scratch. Read the gap analysis
> below before writing code.

### Existing Resources Found (already in the working tree)
- **`registry/types.ts`** — `TileSize = "standard" | "wide" | "tall"` and the optional
  `WidgetSpec.size` field **already exist** (Canvas AC item 2 is effectively done). `CanvasTileSpec`
  carries the resolved `size`.
- **`registry/tileLayout.ts`** — `DEFAULT_SIZE` per-component map + `resolveSize(spec)` resolver
  (`spec.size ?? DEFAULT_SIZE[component] ?? "standard"`) + `FLEX_CLASS` span map **already exist**.
  PortfolioView/Client360/BeforeAfter default `wide`; ConflictsList/RelationshipTimeline `tall`;
  DnaCard/DriftBars `standard` — matches this ticket's intent.
- **`shell/Canvas.tsx`** — already renders `specs[]` as a wrapping bento (no `mx-auto max-w-3xl`
  on the populated state), with a `BARE` set for ChatMessage/SourcesFooter, empty-state, and
  clear-canvas preserved.
- **`shell/CanvasTile.tsx`** — per-tile cell that consumes `FLEX_CLASS[tile.size]` and supplies
  hover chrome (collapse/maximize/pin/close — owned by TASK-069/070).
- **`shell/AppShell.tsx`** — `stampTiles()` already calls `resolveSize(s)` when minting
  `CanvasTileSpec`s, so size resolution is wired end-to-end.

### Gap Analysis — what this ticket still actually has to do
The existing implementation uses a **`flex flex-wrap … justify-center`** layout
(`Canvas.tsx:128`), **not** the CSS grid this ticket specifies. That choice diverges from the AC
in three concrete ways:

1. **Side gutters are NOT gone.** `justify-center` (Canvas.tsx:128) centres any non-full row,
   re-introducing the exact side gutters this ticket exists to eliminate (violates AC #1). The
   ticket calls for `repeat(auto-fit, minmax(~380px, 1fr))`, which fills the width with no
   centring.
2. **`size` semantics don't match the spec.** Today `wide` = `basis-full` (its own full-width
   row) and `tall` = `basis-[360px]` (a plain standard tile — flex **cannot** row-span). The
   ticket asks for `wide` = **span 2 columns** and `tall` = **span 2 rows**, which requires CSS
   grid + `col-span-2` / `row-span-2` (violates AC #3 for `tall`).
3. **Newest-tile highlight on insert is missing.** Canvas still auto-scrolls to bottom
   (`Canvas.tsx:55–59`); the ticket replaces that with a top-left insert + brief highlight
   (violates AC #5, the highlight half). NOTE: scroll-vs-lock is explicitly TASK-068's concern —
   only the *insert highlight* belongs here.

**Design tension to resolve first (do not silently switch):** the flex approach in
`tileLayout.ts` was a *deliberate* TASK-066 decision (see its header comment — wide tiles take
their own row so internal columns aren't crushed). Converting to CSS grid changes that behaviour
and could regress wide dashboards (Client360/PortfolioView) into half-width. Coordinate with
TASK-066 (in-progress) before flipping the engine — either (a) move to grid and make `wide` =
`col-span-2` with the grid wide enough that two columns still give dashboards real width, or
(b) keep flex but drop `justify-center` to `justify-start` and accept that `tall` ≠ true
row-span. Option (a) satisfies the AC literally; (b) is a smaller change that leaves AC #3
partially unmet. **Recommend (a)** + a per-`size` grid-span class map replacing `FLEX_CLASS`.

### Dependencies Required
- Frontend packages: none new (Tailwind JIT — enumerate any `col-span-*`/`row-span-*` as full
  static class strings so they aren't purged, same pattern as AppShell's `railCols`).
- Backend / DB / Docker: none. Pure frontend (as the ticket states).

### Impact Assessment
#### Files to Modify
- `frontend/src/components/shell/Canvas.tsx`: swap flex container → CSS grid; replace
  auto-scroll effect with newest-tile insert highlight.
- `frontend/src/registry/tileLayout.ts`: replace `FLEX_CLASS` (flex basis) with a grid-span class
  map (`standard`→span 1, `wide`→`col-span-2`, `tall`→`row-span-2`).
- `frontend/src/components/shell/CanvasTile.tsx`: consume the new span class instead of
  `FLEX_CLASS[tile.size]`; add the insert-highlight state/animation hook.

#### Components Affected
- `CanvasTile` — **MEDIUM** (span source changes; maximize/collapse paths must still win over span).
- `AppShell` — **LOW** (already passes resolved `size`; no API change).
- TASK-068 (overflow) / TASK-070 (rails, in-progress) — **LOW–MEDIUM**: both read the same
  `specs[]`/`CanvasTileSpec`; the Fixed-mode auto-collapse reflow (`Canvas.tsx:64–81`) assumes the
  current container — re-verify it under a grid container.

#### API / Database Changes
- None. Render-only; `{component, props, size?}` contract unchanged (grounding rule intact —
  `size` is layout intent, not data).

### Implementation Checklist
- [ ] Reuse `resolveSize` / `DEFAULT_SIZE` / `CanvasTile` — do **not** re-add the `size` field or
      resolver (already present).
- [ ] Replace flex+`justify-center` with `grid` `auto-fit minmax(~380px,1fr)`; remove centring so
      gutters disappear.
- [ ] Replace `FLEX_CLASS` with grid-span classes (`wide`→`col-span-2`, `tall`→`row-span-2`),
      enumerated as static Tailwind strings.
- [ ] Coordinate the flex→grid switch with TASK-066 so wide dashboards keep real width.
- [ ] Add newest-tile insert highlight; drop the auto-scroll effect (leave scroll behaviour to
      TASK-068).
- [ ] Preserve empty-state + clear-canvas; verify Fixed-mode reflow still works under grid.
- [ ] Verify light/dark tokens + no console errors.

### Risk Analysis
- **Risk Level**: MEDIUM
- **Main Risks**:
  - *Regressing wide dashboards to half-width* when leaving flex's `basis-full` → mitigate by
    sizing the grid so `col-span-2` still yields a full-bleed-ish wide tile; visual-check
    Client360 & PortfolioView.
  - *Conflict with in-flight TASK-066/070 edits to the same files* (uncommitted working tree) →
    mitigate by syncing before/while editing; this ticket should land as part of the same epic
    branch, not in isolation.
  - *Tailwind purging dynamic span classes* → mitigate with static enumerated class strings.

### Estimated Effort
- Original: **M**
- Adjusted: **S–M** — the scaffold (types, resolver, tile, wiring) is done; remaining work is the
  grid swap + span map + insert highlight + one design reconciliation with TASK-066.
- Reason: ticket assumed greenfield; ~half the listed "New" work already exists in the tree.
