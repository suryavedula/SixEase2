# TASK-062: Hyper-personalisation & quarterly improvement radar [PARENT]

**Status:** BACKLOG · **Epic:** EPIC-10 · **Priority:** P1 · **Type:** feature · **Effort:** L · **Created:** 2026-06-20

## Description
One swap engine, three entry points — surface and apply DNA-driven instrument personalisation
that **never leaves the CIO mandate**. The mechanic already exists (`fit.py` → `swap.py`,
CIO-BUY-only, mandate-neutral, ≥10pp `fit_gain` gate); this epic exposes it at three scopes:

| Entry point | Scope | When | "Before" is… |
|---|---|---|---|
| Improvement radar | whole book | periodic (quarterly, ~CIO-list cadence) | current holdings, ranked |
| Simulated new client | one new client | on demand (demo seed) | the house/model portfolio |
| Before/after view | one client | on open | current holdings · or model portfolio |

This is a **separate feed from the Change Radar (EPIC-08 / TASK-058)**. Change Radar is
event/news-driven and book-wide-by-exposure; this radar is DNA/fit-driven and gated by available
`fit_gain`. They may share an inbox shell later, but logic, trigger, and ranking stay independent.

## Business value
- Personalisation-at-scale: a periodic, pre-gated list of "clients where a real improvement
  exists" — 8 worth a call, not 100 rows of noise.
- The strongest single-screen pitch: **values honoured, fully within CIO** — one axis moves
  (which instruments, for the client's DNA), one axis frozen (the strategy weights, per CIO).
- Onboarding-style "wow" via a simulated client: house model vs. personalised fill, same risk.
- Human-in-the-loop: every row/swap ends in an RM action; nothing reaches the client automatically.

## Sub-tasks
- [ ] TASK-063: Improvement-radar API — batch swap-engine sweep across the book (backend)
- [ ] TASK-064: Simulated-client seeder + house-model baseline for before/after (backend)
- [ ] TASK-065: Before/After portfolio widget — "values honoured, within CIO" (frontend)

## Completion criteria
All three complete: a quarterly-cadence radar lists improvable clients ranked by impact and
gated by ≥10pp fit-gain; a seeded persona (notes + mandate) yields a personalised portfolio vs.
the house model; and the before/after widget renders both modes with the values+CIO headline.

## Existing resources to reuse
`fit.py` (fit scorer) · `swap.py` (SwapProposal engine, ≥10pp gate, mandate-neutral) ·
`drift.py` · `tags.py` (value tags) · `persona_portfolio.py` (persona→holdings link) ·
`/clients/{id}/portfolio/{fit,swaps,allocation}` endpoints · `PortfolioView.tsx` (current
before/after logic) · deleted `SwapBeforeAfter.tsx` (git history) · `WidgetContainer` ·
`CanvasActions` · registry.ts.

## Open decisions (carry into sub-tasks)
- Radar ranking: `fit_gain × exposure_chf_in_slot`, then "why now" tiebreak. Tune in TASK-063.
- "Why now" signal source: new CIO-list version vs. new CRM notes shifting DNA since last review.
- Cadence trigger: standing quarterly sweep vs. event nudge (new CIO list) — pick in TASK-063.
- Widget name working title ("Before/After", "Fit Studio") — finalise before demo.

## Refs
docs/Requirements.md §UC-1/UC-4/UC-27, E5–E12 · backend/app/loaders/{fit,swap,drift,tags}.py ·
frontend/src/components/widgets/PortfolioView.tsx · EPIC-08 (Change Radar, the *other* feed)
