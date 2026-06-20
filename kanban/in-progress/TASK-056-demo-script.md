# TASK-056: Demo script (signature scene)

**Status**: IN-PROGRESS · **Epic:** EPIC-14 · **Priority:** P0 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Script the signature scene: one news event yielding two different human responses across two personas (a swap and a call), each traceable; plus the book-view scale shot.

## Acceptance Criteria
- [ ] one-event-two-clients scene runs reliably
- [ ] traceability visible on screen (G2)
- [ ] book view shows personalization at scale

## Dependencies
TASK-055, TASK-024, TASK-040

## Refs
Requirements §9 (demo scene), §12

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

**Backend — all live or in-progress:**
- `POST /admin/seed/personas` (`routers/admin.py:TASK-055`) — full 14-step pipeline for 4 personas; idempotent
- `GET /book` (`routers/book.py`) — 107 clients sorted by value-weighted fit score
- `GET /clients/{id}/alerts` (`routers/alerts.py`) — ranked alert queue per client
- `GET /clients/{id}/portfolio/swaps` (`routers/portfolio.py`) — DNA-conflict swap proposals
- `GET /drafts/{id}` + `PATCH + POST .../approve` (`routers/messages.py`, TASK-040 in-progress) — message draft CRUD
- `app/loaders/news_seed.py` — 4 scripted D3 articles (one per persona); idempotent by `event_cluster_id`
- Seeded Räber article: "Intel Posts Fourth Consecutive Quarter of Revenue Decline" → `matched_holdings: [Intel]`, `matched_themes: ["us-tech"]`
- Seeded Ammann article: "LVMH and Richemont Report Record Q2 Sales" → `matched_themes: ["luxury"]`, `sentiment: +0.88`

**Frontend — all live:**
- `AppShell` + `ActionCenter` — fetches all alerts from all clients on mount; `AlertCard` shows client name, severity, action type; "Rebalance" / "Draft Message" buttons open `DEFAULT_VIEW_SPECS[prefs.defaultView](clientId)` on Canvas
- `InputDock.resolveSlashCommand` — handles `/client {name}`, `/book`, `/portfolio`, `/note`, `/research`; posts to orchestrator for NL
- `SwapBeforeAfter` widget — shows Before/After panels + proof strip (DNA chip + CIO view + Mandate-neutral badge) + `SourcesFooter` — **traceability already built**
- `BookList` widget — 107 expandable rows sorted by fit with top-3 swap proposals — **scale shot already built**
- `MessageDraftWidget` (TASK-040) — draft body + provenance chips + approve/edit/handoff — **in-progress**

### Gap Analysis

**Gap 1 — `/swaps` slash command missing from InputDock**
`resolveSlashCommand` has no `/swaps` handler. The demo presenter can't type `/swaps Räber` to jump directly to `SwapBeforeAfter`. The only current path is: click an alert in ActionCenter → opens `DEFAULT_VIEW_SPECS` (DnaCard + ConflictsList, not SwapBeforeAfter). This needs a one-line addition.

**Gap 2 — `/draft` slash command missing from InputDock**
No handler for `/draft {name}` → `MessageDraftWidget`. Needed for the "call Ammann" beat. Depends on TASK-040 delivering `MessageDraftWidget`.

**Gap 3 — "One event, two clients" literalness**
Existing seeds have SEPARATE articles per persona. For the Intel article to fire for Ammann too, he needs "us-tech" in his watchlist themes (LLM-extracted from DNA). This is unreliable if Ollama isn't warm. Safer: a 5th seeded article in `news_seed.py` that explicitly targets both clients by combining their themes in a single story. See Deliverable 4.

**Gap 4 — No single-command demo reset**
Running 14 seed steps in order before a live demo is error-prone. A `POST /admin/demo/seed` endpoint that calls `seed_personas → seed_synthetic → seed_news → seed_alerts → seed_rank` in order and returns a state summary is needed.

### Dependencies Required
- Backend packages: none new
- Frontend packages: none new
- Database migrations: none — all tables exist
- Docker services: `postgres`, `redis`, `ollama` (for personas pipeline)
- Seeding order: `POST /admin/demo/seed` (new composite endpoint) covers everything

### Impact Assessment

#### Files to Create
- `docs/demo-script.md` — narrated step-by-step demo guide (primary deliverable)

#### Files to Modify
- `backend/app/loaders/news_seed.py` — add 5th seeded article "Tech Sector Rotation" that combines Intel decline + ASML gain, with `matched_holdings: [Intel/Räber]` and `matched_themes: ["us-tech", "semiconductors"]` so it fans out to Ammann if his watchlist includes either theme
- `backend/app/routers/admin.py` — add `POST /admin/demo/seed` composite endpoint (calls seed_personas → seed_synthetic → seed_alerts → seed_rank in order; returns state summary with alert counts per persona)
- `frontend/src/components/shell/InputDock.tsx` — add `/swaps {name}` handler → `[{ component: "SwapBeforeAfter", props: { clientId: resolvedId } }]`; add `/draft {name}` handler → `[{ component: "MessageDraftWidget", props: { ... } }]` (gated on TASK-040 shipping `MessageDraftWidget`)

#### Components Affected
- `news_seed.py`: LOW — additive only (5th article); idempotent insert, no schema changes
- `routers/admin.py`: LOW — additive only (new endpoint)
- `InputDock.tsx`: LOW — additive only (2 new slash-command branches); no state changes
- All existing widgets/endpoints: **unaffected**

#### API Changes
- **New:** `POST /admin/demo/seed` → `{ "status": "ok", "personas": {...summary}, "synthetic": {...}, "alert_counts": { "Räber": N, "Schneider": N, "Huber": N, "Ammann": N } }`

#### Database Changes
- None beyond what the existing seed endpoints write.

### Demo Scene Design

**Personas:** Eugen Räber (Defensive) · Julian Ammann (Growth)

**The event:** Intel earnings decline (seeded 2026-06-19)
- Räber holds Intel (CIO SELL, `dna_conflict` / `swap_trigger` alert) → RM proposes a swap
- Ammann has "us-tech" or "semiconductors" in his watchlist themes → `news_impact` alert on the same story → RM reaches out with a values-led message

**Act 1 — Setup (30 s)**
```
POST /admin/demo/seed
```
Returns 4 personas populated, ~107 clients total, alerts ranked. Confirm with: ActionCenter badge shows > 0.

**Act 2 — Alert Queue (20 s)**
ActionCenter opens on load; narrator: "The system surfaced these this morning — ranked by urgency."
Filter "Clients" → Räber tops the list (Intel `swap_trigger`, Critical or Attention).

**Act 3 — The Swap (60 s)**
Type `/swaps Räber` in InputDock OR click "Rebalance" on Räber's alert.
Canvas shows `SwapBeforeAfter`:
- Before: Intel, fit 0% (us-tech exclusion from DNA), CHF value
- After: [CIO BUY replacement, same Industry Group], projected fit ↑, "+Npp"
- Proof strip: "Mandate neutral" badge + DNA chip: "{exclusion reason from CRM}" + CIO chip: "BUY · {view}"
- SourcesFooter: CRM note citation + CIO recommendation row
Narrator: "Every number comes from a data tool. The model arranged the widget; the RM approves the trade."

**Act 4 — The Call (60 s)**
Type `/client Ammann` then `/draft Ammann` in InputDock.
Canvas shows `DnaCard` (luxury tilt, ESG inclination) then `MessageDraftWidget`:
- Draft body: personalised reach-out about Intel news + Ammann's clean portfolio
- Provenance panel: chips for each `provenance[]` entry (CRM note · news article · DNA tilt)
- Approve → status flips to APPROVED
- Handoff: mailto opens with draft body pre-filled
Narrator: "Same news event. Same strategy. Two completely different actions — because they're different people."

**Act 5 — Scale (30 s)**
Type `/book` in InputDock.
Canvas shows `BookList`: 107 rows sorted by fit. Each row: client name + mandate badge + fit bar + conflict count + swap count.
Expand two rows to show different top-3 proposals.
Narrator: "Every single client gets a personalised view. One strategy. 107 people. The RM never breaks the mandate."

### Implementation Checklist
- [ ] Add 5th seeded article to `news_seed.py` (Intel + semiconductors / us-tech combined story)
- [ ] Add `/swaps {name}` slash command to `InputDock.tsx` → `SwapBeforeAfter`
- [ ] Add `/draft {name}` slash command to `InputDock.tsx` → `MessageDraftWidget` (ships when TASK-040 done)
- [ ] Add `POST /admin/demo/seed` to `routers/admin.py` (composite: personas → synthetic → alerts → rank)
- [ ] Write `docs/demo-script.md` with exact commands, narration notes, and fallback instructions
- [ ] Smoke-test full scene end-to-end: seed → alert appears for Räber AND Ammann from same event → both widgets render correctly
- [ ] Verify traceability: SwapBeforeAfter proof strip shows DNA + CIO sources; MessageDraftWidget provenance chips link to CRM/news
- [ ] Verify book view: `/book` returns 107 rows sorted by fit, top-3 swap proposals visible on expand
- [ ] Add fallback instructions to demo script: if Ammann watchlist miss → use Ammann's LVMH article as "the call" trigger (still demonstrates two personas, two responses from morning queue)

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - *Ammann watchlist doesn't include "us-tech"* — the Intel article doesn't fan out to him; no `news_impact` alert fires. Mitigation: 5th seeded article adds explicit `matched_themes: ["semiconductors"]`; if still misses, fallback to luxury article for Act 4 (still demonstrates "two clients, two responses").
  - *TASK-040 `MessageDraftWidget` not yet shipped* — Act 4 can't show provenance panel. Mitigation: Act 4 shows `DnaCard` + `RelationshipTimeline` (shows CRM notes) instead; still demonstrates traceability. Add `/draft` command gated: shows "TASK-040 pending" FallbackCard if component not registered.
  - *Ollama not running during demo* — Steps 4/5/14 of personas pipeline fail (DNA + style + message render). Mitigation: `POST /admin/demo/seed` returns partial success summary; Acts 3–4 still work if seed/fit + seed/swap ran (all pure-SQL steps). Pre-warm Ollama before demo.
  - *`MessageDraft.draft_text = null`* — message not yet rendered. Mitigation: widget shows "pending render" state with a trigger button (already designed in TASK-040); RM clicks trigger in front of audience — turns LLM latency into a live demo moment.

### Estimated Effort
- Original: S
- Adjusted: S
- Reason: All widgets and endpoints exist or are in-progress. Deliverables are: 1 document, 1 small backend endpoint, 2 frontend command handlers, 1 seeded article. No new architecture.
