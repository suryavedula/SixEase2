# TASK-045: In-UI explainability

**Status:** IN-PROGRESS · **Epic:** EPIC-10 · **Priority:** P0 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Every widget can expand to show its sources (CRM note, news article, CIO view, SIX price) so the why travels with the view.

## Acceptance Criteria
- [ ] each widget exposes its sources on expand
- [ ] sources link to underlying records
- [ ] consistent across widget types

## Dependencies
TASK-041 (IN-PROGRESS — registry + WidgetRenderer must land first; files exist but task not closed)

## Refs
Requirements §17 UI-8, G2/G3

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **Reference implementation — DnaCard (COMPLETE):**
  - `frontend/src/components/widgets/DnaCard.tsx` already implements the full expand-to-sources pattern:
    - Per-item chips click to expand inline CRM note (date · medium · excerpt)
    - Widget-level "▼ Sources (N)" footer that expands a `RelationshipTimeline`
    - Driven by `DnaItem.source_note_ids[]` → hydrated `DnaSource[]` from backend
  - This is the design reference for all other widgets.

- **Backend citation infrastructure (COMPLETE):**
  - `backend/app/models/citation.py` — polymorphic `Citation` table (`owner_type` / `owner_id` / `source_type` / `source_id` / `note`)
  - `SourceType` enum: `crm_note`, `news`, `cio` (covers all required source types; SIX price is live data, not a citation row)
  - DNA endpoint (`GET /clients/{id}/dna`) already hydrates and returns `sources: DNASource[]` — proves the pattern works end-to-end
  - `Alert.evidence` JSONB field carries source references for news/CRM triggers

- **Components to reuse:**
  - `RelationshipTimeline` — already used by DnaCard as the expanded sources view; can be reused by DnaRadar for the same DNA sources
  - `WidgetRenderer` / `FallbackCard` from registry (TASK-041) — no changes needed here
  - All 13 registered widgets are the modification targets

- **APIs already returning sources:**
  - `GET /clients/{id}/dna` — `sources: DNASource[]` ✅
  - `GET /clients/{id}/alerts` — `evidence: list | None` on each alert ✅ (raw JSONB, not hydrated)
  - `GET /clients/{id}/portfolio/swaps` — `SwapProposal.sources: list | None` exists on the model; **not yet in the API response** (gap)

- **Source availability by widget:**
  | Widget | Source type | Backend status |
  |---|---|---|
  | `DnaCard` | CRM notes | ✅ done — no changes needed |
  | `DnaRadar` | CRM notes (same DNA) | needs sources footer added |
  | `RelationshipTimeline` | CRM interactions | IS the source display; add "full note" expand per row |
  | `ConflictsList` | CRM notes (via DNA exclusions) | needs `sources` from DNA endpoint (already available) |
  | `SwapBeforeAfter` | CIO recommendation (`cio_view` text + rating) | need to expose `sources` in `/portfolio/swaps` response |
  | `HoldingsTable` | CIO recommendation (per holding's `industry_group`) | need per-row CIO source lookup or inline in fit response |
  | `FitHeatmap` | CIO recommendation (same as above) | same gap as HoldingsTable |
  | `DriftBars` | Mandate strategy weights (computed) | static label "Source: CIO Mandate Strategy" — no record link |
  | `AllocationDonut` | Mandate strategy weights (computed) | static label only |
  | `SectorTreemap` | CIO tags (computed aggregate) | static label only |
  | `BookList` | Aggregate RM-level view | static label "Source: Portfolio positions" — no per-record link |
  | `MessageDraftPanel` | DNA + news | forward `sources` from draft payload |
  | `MessageDraftWidget` | DNA + news | same as above |

### Dependencies Required

- **Frontend packages:** None — zod v4.4.3 already installed; all needed UI primitives exist
- **Backend packages:** None — SQLAlchemy, Pydantic, Citation model all in place
- **Database migrations:** None — `citations`, `interactions`, `news_items`, `cio_recommendations` tables all exist
- **Docker services:** None

### Impact Assessment

#### Files to Create (new)
- `frontend/src/components/widgets/SourcesFooter.tsx` — shared expand/collapse "▼ Sources (N)" component; takes `sources: Source[]` and a render-prop for each row; used by all widgets for consistency (AC3)

#### Files to Modify

**Frontend:**
- `frontend/src/components/widgets/DnaCard.tsx` — refactor footer to use `SourcesFooter` (behaviour unchanged; deduplication)
- `frontend/src/components/widgets/DnaRadar.tsx` — fetch DNA endpoint (already client-side), add `SourcesFooter` showing same CRM notes
- `frontend/src/components/widgets/RelationshipTimeline.tsx` — add per-row "▼ full note" toggle showing complete `note` text (row already displays date/medium/excerpt)
- `frontend/src/components/widgets/ConflictsList.tsx` — co-fetch `GET /clients/{id}/dna`, add `SourcesFooter` with CRM notes that drove the exclusion tags
- `frontend/src/components/widgets/SwapBeforeAfter.tsx` — add `SourcesFooter` listing CIO source once `/portfolio/swaps` exposes it
- `frontend/src/components/widgets/HoldingsTable.tsx` — add per-row expandable CIO source inline (issuer → `cio_view` text from fit response, if extended)
- `frontend/src/components/widgets/FitHeatmap.tsx` — same CIO source reveal as HoldingsTable
- `frontend/src/components/widgets/DriftBars.tsx` — static "Source: CIO Mandate Strategy" chip (no expand, no link — computed from weights table)
- `frontend/src/components/widgets/AllocationDonut.tsx` — same static chip
- `frontend/src/components/widgets/SectorTreemap.tsx` — same static chip
- `frontend/src/components/widgets/BookList.tsx` — static "Source: Portfolio positions" chip
- `frontend/src/components/widgets/MessageDraftPanel.tsx` — expose `sources` from draft payload in SourcesFooter
- `frontend/src/components/widgets/index.ts` — export `SourcesFooter`
- `frontend/src/api/portfolio.ts` — update `SwapProposalItem` type to include `sources: SwapSource[] | null`

**Backend:**
- `backend/app/routers/portfolio.py` — extend `SwapProposalItem` Pydantic model + serialization to include `sources` from `SwapProposal.sources` JSONB; add a `cio_view` field to `HoldingFit` via a JOIN to `cio_recommendations` on `industry_group`

#### Components Affected
- `SourcesFooter` (new) — HIGH (owns the consistent expand pattern; all widgets delegate to it)
- `DnaCard` — LOW (refactor footer only; rendered output identical)
- `DnaRadar`, `ConflictsList`, `SwapBeforeAfter`, `HoldingsTable`, `FitHeatmap` — MEDIUM (add sources fetch + footer)
- `RelationshipTimeline` — LOW (per-row expand only, no new fetch)
- `DriftBars`, `AllocationDonut`, `SectorTreemap`, `BookList` — LOW (static label chip)
- `MessageDraftPanel`, `MessageDraftWidget` — LOW (forward existing sources field)
- `WidgetRenderer`, `registry` — no changes

#### API Changes
- `GET /clients/{id}/portfolio/swaps` — add `sources: list[SwapSource] | null` to each swap proposal item in response
- `GET /clients/{id}/portfolio/fit` — add `cio_view: str | null` to each `HoldingFit` row (JOIN to `cio_recommendations` on `industry_group`)

#### Database Changes
None. All source data is already in `cio_recommendations`, `interactions`, `news_items`.

### Implementation Checklist
Based on CLAUDE.md principles:
- [ ] Create `SourcesFooter` as the single shared expand component — zero per-widget duplication
- [ ] Reuse `RelationshipTimeline` in `DnaRadar` for CRM notes (same component DnaCard uses)
- [ ] Reuse the `DnaCard` footer pattern (now via `SourcesFooter`) for `ConflictsList` — both use CRM notes from the DNA endpoint
- [ ] Extend `/portfolio/swaps` serializer; no model change needed (`sources` field already on `SwapProposal`)
- [ ] Add `cio_view` JOIN in `/portfolio/fit` — single LEFT JOIN to `cio_recommendations` on `industry_group`; no N+1
- [ ] Static "Source:" chips for computed widgets — no new API calls
- [ ] Follow existing widget loading/error skeleton pattern in all modified widgets
- [ ] Write self-documenting code

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - **DnaRadar co-fetch**: DnaRadar will call `GET /clients/{id}/dna` in addition to its own data source. If DNA hasn't been seeded, it must degrade gracefully (show "Sources unavailable"). **Mitigation:** wrap the DNA fetch in a separate `useState`; sources absence never blocks the radar render.
  - **TASK-041 not fully closed**: `WidgetRenderer` files exist but TASK-041 is still IN-PROGRESS. TASK-045 does not touch the registry; it modifies widget internals only. Safe to develop in parallel but must not be merged before TASK-041 closes.
  - **`cio_view` JOIN performance**: `portfolio/fit` already queries `enriched_holdings`; a LEFT JOIN on `industry_group` is a string match across ~172 CIO rows. Acceptable for hackathon scale; add `ix_cio_industry_group` index (already exists in migration `0003_cio_tags`). **No risk.**

### Estimated Effort
- **Original:** S
- **Adjusted:** S (unchanged — shared component + 5 backend lines + per-widget wiring)
- **Reason:** DnaCard proves the pattern; `SourcesFooter` is the only genuinely new component. All source data exists; two small backend serializer extensions cover the gaps.
