# TASK-039: Channel-awareness and email handoff

**Status:** IN-PROGRESS · **Epic:** EPIC-09 · **Priority:** P1 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Suggest the right channel (call/email/in-person; emotional moments prefer a call); provide one-click Outlook-draft/copy handoff. Test sends via MailHog. Never auto-send.

## Acceptance Criteria
- [ ] channel suggested per moment (MSG8)
- [ ] open-as-draft handoff works (MSG9)
- [ ] nothing auto-sent (G1)

## Dependencies
TASK-038, TASK-005

## Refs
Requirements §16 MSG8/MSG9

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **`MessageDraft` model** (`app/models/derived.py:116`) — already has `channel: str | None`
  and `draft_text: str | None` fields. TASK-039 fills `channel` at fact-sheet assembly time
  and uses `draft_text` (populated by TASK-038) for the email handoff body. No schema change
  needed.
- **`Moment` model** (`app/models/derived.py:156`) — also has `channel: str | None`. Same
  channel-selection logic applies here.
- **`DraftStatus` enum** (`app/models/enums.py:55`) — already has `draft`, `approved`, `sent`,
  `dismissed`. No new values needed.
- **`assemble_fact_sheet` loader** (`app/loaders/fact_sheet.py`) — creates `MessageDraft` with
  `channel=None`. This is the injection point for MSG8 channel selection.
- **`POST /admin/assemble/fact-sheet`** (`app/routers/admin.py:346`) — existing endpoint;
  will expose `channel` in its response once the loader populates it.
- **MailHog service** (`docker-compose.yml:85`) — already running on the `wealthnet` network;
  SMTP at `mailhog:1025`, web UI at port `${MAILHOG_UI_PORT}`. No compose changes needed.
- **`Settings`** (`app/config.py`) — no SMTP fields yet; `MAILHOG_SMTP_PORT` is in `.env.example`
  only for compose (host-published). Need to add `mailhog_host`/`mailhog_smtp_port` fields for
  the app (container-facing, `mailhog:1025`).
- **ActionCenter.tsx** (`frontend/src/components/shell/ActionCenter.tsx:33`) — already maps
  `ReachOut` alert action to label `"Draft Message"`, but the button is a no-op stub. This is
  the primary wiring point for the handoff UI.
- **`alerts.ts` API client** (`frontend/src/api/alerts.ts`) — existing; no changes needed.

### Dependencies Required

- **Backend packages to add:**
  - `aiosmtplib>=3.0.1` — async SMTP client for MailHog test-send. Same pattern as
    `redis.asyncio` used in TASK-005.
- **Frontend packages:** none — `mailto:` links are native browser; clipboard API is built-in.
- **Database migrations:** none — `channel` column already exists on `message_drafts`.
- **Docker services:** `mailhog` — already running (docker-compose.yml). No compose changes.

### Impact Assessment

#### Files to Create
- `backend/app/loaders/channel.py` — pure function `suggest_channel(alert_class, moment_type)
  -> str` that returns `"call"` / `"email"` / `"in-person"`. Emotional alert classes
  (`good_news`, `quiet_client`, `overdue_promise`, `panic`) → `"call"` per MSG8; financial
  classes (`dna_conflict`, `values_drift`, `drift_breach`, `stale_sell`, `news_impact`) →
  `"email"`.
- `backend/app/routers/messages.py` — new router with:
  - `GET /drafts/{draft_id}` — return `MessageDraft` fields (text, channel, status, fact_sheet)
  - `POST /drafts/{draft_id}/send-test` — SMTP-send the draft to MailHog; updates
    `status → sent` in DB. Never exposed as auto-send; requires explicit RM call.
- `frontend/src/api/messages.ts` — API client for `getDraft(id)`, `sendTestDraft(id)`.
- `frontend/src/components/widgets/MessageDraftPanel.tsx` — slide-in panel showing:
  - Channel badge (📞 Call / ✉ Email / 🤝 In-person)
  - Draft text (read-only; editable in TASK-038 scope)
  - "Open in Outlook" button → `mailto:` link (subject + body pre-filled)
  - "Copy" button → `navigator.clipboard.writeText(draftText)`
  - "Send test (MailHog)" button → calls `POST /drafts/{id}/send-test`

#### Files to Modify
- `backend/app/loaders/fact_sheet.py` — import `suggest_channel`; populate
  `MessageDraft.channel` at step 9 (persist). Pass `alert.alert_class` to `suggest_channel`.
- `backend/app/config.py` — add `mailhog_host: str = Field(default="mailhog")` and
  `mailhog_smtp_port: int = Field(default=1025, validation_alias=AliasChoices("MAILHOG_CONTAINER_SMTP_PORT"))`.
- `backend/app/main.py` — include the new `messages` router in `lifespan`/router-mount.
- `backend/requirements.txt` — add `aiosmtplib>=3.0.1`.
- `.env.example` / `.env` — add `MAILHOG_CONTAINER_SMTP_PORT=1025`.
- `frontend/src/components/shell/ActionCenter.tsx` — wire the `ReachOut` "Draft Message"
  button to open `MessageDraftPanel` (pass `alert.draft_ref` or call
  `POST /admin/assemble/fact-sheet` then open the panel with the returned `draft_id`).

#### Components Affected
- `ActionCenter.tsx`: **MEDIUM** — button gains real handler; panel mount added.
- `assemble_fact_sheet` loader: **LOW** — one-line addition to populate `channel`.
- `admin.py`: **LOW** — additive: new router mounted, no existing endpoint changed.
- `config.py`: **LOW** — additive fields.

#### API Changes
- `GET /drafts/{draft_id}` — new endpoint, returns `{id, client_id, channel, draft_text,
  fact_sheet, status, created_at}`.
- `POST /drafts/{draft_id}/send-test` — new endpoint; sends via MailHog SMTP; response
  `{status: "sent", mailhog_ui: "http://localhost:8025"}`.
- `POST /admin/assemble/fact-sheet` — response now includes `channel` in the returned dict
  (additive, backwards-compatible).

#### Database Changes
- None — `message_drafts.channel` column already exists.

### Implementation Checklist
- [ ] Reuse `MessageDraft.channel` field (exists) — no new column
- [ ] Add `suggest_channel()` as a standalone function (testable in isolation)
- [ ] Inject channel in `assemble_fact_sheet` (single line, no duplication)
- [ ] SMTP sender in `messages.py` uses `aiosmtplib` (async, mirrors `redis.asyncio` pattern)
- [ ] `mailto:` handoff is pure frontend — no backend round-trip
- [ ] `POST /drafts/{id}/send-test` updates `status → "sent"` (not `approved`) — MailHog only
- [ ] MailHog endpoint is inside compose network (`mailhog:1025`) — no host-port confusion
- [ ] Nothing auto-sends — the endpoint requires an explicit RM action (G1 / MSG7)
- [ ] Channel badge is display-only on the draft panel; not editable (RM overrides via Outlook)
- [ ] `aiosmtplib` rebuild needed after `requirements.txt` change

### Risk Analysis
- **Risk Level:** LOW–MEDIUM
- **Main Risks:**
  - *TASK-038 not done* — `draft_text` will be `None` until TASK-038 populates it. Mitigation:
    `mailto:` and copy buttons fall back gracefully ("Draft not yet generated — run LLM render
    first"); MailHog test-send skips the email body when `draft_text` is None but still sends
    the fact-sheet summary so the handoff flow is demonstrable.
  - *`mailto:` URL length limit* — some mail clients cap at ~2 000 chars; long drafts get
    truncated. Mitigation: truncate body at 1 800 chars with "…(truncated)" for the mailto
    path; offer "Copy" as the full-text fallback.
  - *`aiosmtplib` image rebuild* — same issue as TASK-005 Redis/MinIO: code-only bind-mount
    reload won't pick up new deps. Run `docker compose build backend` after requirements change.

### Estimated Effort
- Original: **S**
- Adjusted: **S** — `channel` column exists, MailHog is live, the DB schema needs no migration.
  New work is the channel-selection function, async SMTP sender, and 3 frontend pieces
  (API client + panel + button wiring). All self-contained.
