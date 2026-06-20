# TASK-040: Message widget

**Status:** IN-PROGRESS · **Epic:** EPIC-09 · **Priority:** P0 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Widget: draft text + provenance panel + data-driven/values-led toggle (same facts, two renders) + approve/edit/handoff actions.

## Acceptance Criteria
- [ ] toggle re-renders style without changing facts
- [ ] provenance chips link to sources
- [ ] approve/edit/handoff actions present

## Dependencies
TASK-003, TASK-038, TASK-041

## Refs
Requirements §18.2, §16

---

## Technical Analysis (Auto-generated 2026-06-20)

### Dependency Status

- **TASK-003** (React skeleton) — ✅ Fully implemented. All shell components, API client helpers (`apiGet`, `apiPost`, `apiPatch`), Tailwind tokens, and widget patterns are live.
- **TASK-038** (LLM render in style + guardrail) — ⚠️ IN-PROGRESS, backend files not yet created (`message_render.py`, `POST /admin/render/message` endpoint). TASK-040's **style toggle** calls this endpoint; the widget must handle `draft_text = null` gracefully (show "Render pending" state, with a manual trigger button).
- **TASK-041** (Component registry) — BACKLOG. The widget is built standalone (consistent with all other current widgets). It will slot into the registry when TASK-041 ships.

### Existing Resources Found

- **`MessageDraft` ORM** (`backend/app/models/derived.py:116`) — all columns already exist: `draft_text Text`, `fact_sheet JSONB`, `facts_used JSONB`, `provenance JSONB`, `style Text`, `channel Text`, `status DraftStatus`. **No migration needed.**
- **`DraftStatus` enum** (`backend/app/models/enums.py:55`) — values: `draft`, `approved`, `sent`, `dismissed`.
- **`assemble_fact_sheet` loader** (`backend/app/loaders/fact_sheet.py`) — creates `MessageDraft` rows with `fact_sheet` populated; `draft_text` is `null` until TASK-038 renders. This is the seeding entry point.
- **`POST /admin/assemble/fact-sheet`** (`backend/app/routers/admin.py:346`) — existing endpoint; returns `{draft_id, client_id, fact_sheet, has_proposal}`. No change needed.
- **Widget patterns** — `SwapBeforeAfter.tsx`, `DnaCard.tsx`: established loading/error state pattern, expandable provenance chips (DnaCard), `AbortController` teardown. All directly reusable.
- **API helpers** — `apiGet`, `apiPost`, `apiPatch` in `frontend/src/api/client.ts`. Full type-safe fetcher coverage.
- **`ActionCenter.tsx`** (`frontend/src/components/shell/ActionCenter.tsx`) — has a stub `"Draft Message"` button for `ReachOut` alerts. TASK-040 does not wire this (TASK-039 owns the wiring to open the panel from an alert).
- **TASK-039 router** — TASK-039 planned `backend/app/routers/messages.py` but hasn't created it. TASK-040 owns this file since it needs `GET /drafts/{id}` and `PATCH /drafts/{id}` to function.

### Dependencies Required
- **Frontend packages:** none new — all present (`react`, Tailwind tokens, existing API helpers).
- **Backend packages:** none new — `sqlalchemy`, `fastapi`, `pydantic`, `asyncpg` all present.
- **Database migrations:** none — all `message_drafts` columns exist.
- **Docker services:** `postgres` (for MessageDraft reads/writes). No new services.

### Impact Assessment

#### Files to Create
- `backend/app/routers/messages.py` — `GET /drafts/{draft_id}`, `PATCH /drafts/{draft_id}` (edit text), `POST /drafts/{draft_id}/approve`
- `frontend/src/api/messages.ts` — types (`MessageDraftResponse`) + fetchers (`getDraft`, `approveDraft`, `patchDraft`)
- `frontend/src/components/widgets/MessageDraftWidget.tsx` — the full widget

#### Files to Modify
- `backend/app/routers/__init__.py` — (if needed to register the new router)
- `backend/app/main.py` — include `messages.router`
- `frontend/src/components/widgets/index.ts` — export `MessageDraftWidget`

#### Components Affected
- `ActionCenter.tsx`: **LOW** — no change; the "Draft Message" button wiring stays as TASK-039's scope
- `Canvas.tsx`: **LOW** — `MessageDraftWidget` can be added to the client view for smoke-testing (optional, similar to how `SwapBeforeAfter` was added to `Canvas.tsx`)
- `main.py`: **LOW** — additive router mount

#### API Changes
- **New:** `GET /drafts/{draft_id}` → `MessageDraftResponse {id, client_id, draft_text, fact_sheet, facts_used, provenance, style, channel, status, created_at, updated_at}`
- **New:** `PATCH /drafts/{draft_id}` body `{draft_text: str}` → updated `MessageDraftResponse`
- **New:** `POST /drafts/{draft_id}/approve` → `{id, status: "approved"}`
- Note: the toggle calls `POST /admin/render/message?draft_id=<uuid>&preset=<values-led|data-driven>` (TASK-038's endpoint, not yet built). Widget displays a "Re-render in [style]" button that calls this; falls back gracefully if TASK-038 isn't done yet.

#### Database Changes
- None. `PATCH /drafts/{id}` UPDATEs `message_drafts.draft_text`; `POST /drafts/{id}/approve` UPDATEs `status → 'approved'`. All on existing columns.

### Widget Design

Three sections, vertically stacked inside the rounded-[14px] card shell (matching all other widgets):

1. **Header** — title "Advisory Draft" · channel badge (📞 Call / ✉ Email) · status chip (`DRAFT` / `APPROVED`) · style toggle: `[Data-driven] | [Values-led]` (active style highlighted in blue)
2. **Draft body** — `draft_text` (null → "Draft not yet generated — run LLM render first" with a trigger seam); edit mode: `<textarea>` with inline save; view mode: `<pre>` styled with `text-[13px] text-muted leading-relaxed whitespace-pre-wrap`
3. **Provenance panel** — collapsible (▼ Provenance · N sources); inside: grid of chips per `provenance[]` entry; each chip = `fact_key` label; on click → popover/inline expand showing `value` + `source`; `facts_used[]` listed below as a compact list

Action bar (bottom of card):
- **Approve** button (blue): `POST /drafts/{id}/approve` → updates local status to `APPROVED`; disabled when status is already `approved`
- **Edit** button (muted): toggles edit mode; shows Save / Cancel when active
- **Handoff** button (teal): opens `mailto:` with `draft_text` pre-filled as body (defers to TASK-039 for full MailHog integration); channel label shown in button

### Implementation Checklist
- [ ] Create `backend/app/routers/messages.py` — `GET /drafts/{id}`, `PATCH /drafts/{id}`, `POST /drafts/{id}/approve`
- [ ] Mount `messages.router` in `backend/app/main.py`
- [ ] Create `frontend/src/api/messages.ts` — types + fetchers
- [ ] Widget: loading skeleton (3 pulse bars, matching DnaCard/SwapBeforeAfter pattern)
- [ ] Widget: error state — 404 path ("No draft — run `/admin/assemble/fact-sheet` first") + generic error
- [ ] Widget: `draft_text = null` → "pending render" state with a seam for TASK-038 trigger
- [ ] Style toggle — calls `POST /admin/render/message?preset=...` (TASK-038 endpoint); on success, refetch draft; on 404 endpoint (TASK-038 not built), shows "LLM render not yet available"
- [ ] Provenance panel — chips for each `provenance[]` entry; expand on click for source detail
- [ ] `facts_used` list — compact list of cited fact-sheet key paths
- [ ] Edit mode — `<textarea>` + PATCH on Save; `APPROVED` chip disables editing
- [ ] Approve action — `POST /drafts/{id}/approve`; optimistic status update
- [ ] Handoff action — `mailto:` with `draft_text` body + `Advisory Draft for [client]` subject
- [ ] Export `MessageDraftWidget` from `frontend/src/components/widgets/index.ts`
- [ ] Reuse rounded-[14px] + border-border + bg-panel card shell (all existing widgets use this)
- [ ] Follow SOLID: `messages.py` has no LLM imports; single responsibility (CRUD on MessageDraft)

### Risk Analysis
- **Risk Level:** LOW–MEDIUM
- **Main Risks:**
  - *TASK-038 not yet built* — the toggle calls a non-existent endpoint. Mitigation: catch the 404/500 gracefully, show "LLM render not yet available" toast; the rest of the widget (provenance panel, approve/edit/handoff) works independently as TASK-037 already populates `fact_sheet`.
  - *Provenance array empty until TASK-038 runs* — `provenance[]` is null when only fact-sheet is assembled. Mitigation: show "No provenance yet — render draft to generate" when `provenance` is null/empty.
  - *`message_render.py` not yet created* — TASK-038 is IN-PROGRESS but unimplemented; the toggle is a stub that will light up once TASK-038 ships. No TASK-040 code changes needed when TASK-038 lands (it already targets the correct endpoint).

### Estimated Effort
- Original: S
- Adjusted: S–M (bumped to M in practice)
- Reason: The backend router is trivial (CRUD on MessageDraft). The frontend widget has meaningful complexity in the provenance-chip panel (expand/collapse, source linking) and the toggle state machine (pre-render / rendering / rendered). All patterns are established; no new packages.
