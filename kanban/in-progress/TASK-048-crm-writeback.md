# TASK-048: CRM write-back and audio storage

**Status:** IN-PROGRESS · **Epic:** EPIC-11 · **Priority:** P1 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
On RM approval, persist the structured note back to the CRM/Interaction store and apply approved DNA updates; store the voice audio in MinIO. Feeds the DNA on next cycle.

## Acceptance Criteria
- [ ] approved note written back (G7)
- [ ] approved DNA updates applied + versioned
- [ ] audio stored in MinIO

## Dependencies
TASK-047, TASK-018, TASK-005

## Refs
Requirements §19.1 VN2, G7

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **Storage:** `backend/app/storage.py` — `put_object(key, data, content_type)` and `get_object(key)` fully implemented; wraps the MinIO SDK singleton. Use unchanged for audio bytes.
- **CRM model:** `backend/app/models/source.py` — `Interaction` (client_id, date, medium, rm_name, client_contact, note). Writing the approved note back = inserting a new `Interaction` row. No model change needed unless we attach the audio key (see migration below).
- **DNA upsert:** `backend/app/loaders/dna.py` — `extract_dna()` uses `pg_insert(...).on_conflict_do_update(set_={..., "version": ClientDNA.__table__.c.version + 1})`. Delta apply follows the same pattern: merge JSONB lists server-side and bump version.
- **DNA model:** `backend/app/models/derived.py` — `ClientDNA` has `values`, `exclusions`, `tilts`, `life_events`, `promises` (JSONB lists) and `version` (Integer). Ready for incremental append without schema change.
- **Approval precedent:** `backend/app/routers/messages.py` — `POST /drafts/{id}/approve` sets `DraftStatus.APPROVED` and logs the event. Same pattern applies here but with side-effect write-backs.
- **Router registration pattern:** `backend/app/main.py` — routers appended via `app.include_router(...)`. Add one line for the new voice-writeback router.
- **Latest migration:** `0009_alert_lifecycle.py`. Next is `0010`.

### Dependencies Required

- **Backend packages:** No new packages — `minio` SDK already in requirements via TASK-005; `sqlalchemy`, `fastapi`, `pydantic` all available.
- **Database migrations:** `0010_voice_notes.py` — add `audio_key TEXT NULL` column to `interactions` table (stores the MinIO object key when an audio recording is attached).
- **Docker services:** MinIO (running, bucket bootstrapped at startup by TASK-005).
- **Upstream task:** TASK-047 must produce `{ structured_note: {...}, dna_delta: {...}, audio_bytes?: bytes }` and call the commit endpoint on RM approval. TASK-048 defines that API surface.

### Impact Assessment

#### Files to Modify
- `backend/app/models/source.py`: add `audio_key: Mapped[str | None]` to `Interaction`
- `backend/app/loaders/dna.py`: add `apply_dna_delta(session, client_id, delta)` function — appends delta items to existing JSONB lists and bumps version
- `backend/app/main.py`: register new `voice_writeback` router

#### New Files
- `backend/migrations/versions/0010_voice_notes.py` — Alembic migration adding `audio_key` to `interactions`
- `backend/app/routers/voice_writeback.py` — `POST /clients/{client_id}/voice-notes/commit` endpoint

#### Components Affected
- `Interaction` model: LOW impact — additive nullable column, backwards-compatible
- `ClientDNA` loader: MEDIUM impact — new mutation path (`apply_dna_delta`) alongside existing full-extraction path (`extract_dna`)
- `main.py`: LOW impact — one `include_router` line

#### API Changes
- **New:** `POST /clients/{client_id}/voice-notes/commit`
  - Request body: `{ note: { date, medium, rm_name, client_contact, body }, dna_delta: { values?, exclusions?, tilts?, life_events?, promises? }, audio_key?: str }`
  - `audio_key` is the MinIO object key of the already-uploaded audio (upload happens separately via multipart, or TASK-047 uploads before calling commit)
  - Response: `{ interaction_id, dna_version, audio_key }`

#### Database Changes
- `interactions`: add `audio_key TEXT NULL` — nullable; only set when a voice recording is attached

### Implementation Notes

**Audio storage pattern:**  
`useVoiceInput.ts` (TASK-046) uses the browser's SpeechRecognition API and only exposes the `transcript` text — it does NOT capture a raw audio blob. For MinIO audio storage, TASK-047 must also wire `MediaRecorder` to capture the audio bytes and upload them (via multipart `POST /clients/{id}/voice-notes/audio`) before calling the commit endpoint. TASK-048's commit endpoint receives the resulting MinIO `audio_key`, not the raw bytes.  
Key convention: `voice-notes/{client_id}/{interaction_id}.webm`

**DNA delta merge pattern** (in `apply_dna_delta`):
```python
# Append new items to existing JSONB arrays, bump version
stmt = (
    pg_insert(ClientDNA)
    .values(client_id=client_id, ...)
    .on_conflict_do_update(
        index_elements=["client_id"],
        set_={
            "values": func.jsonb_concat(ClientDNA.values, delta.values),
            "version": ClientDNA.__table__.c.version + 1,
            "updated_at": func.now(),
        },
    )
)
```
Use `func.jsonb_concat` (Postgres `||` operator) so existing items are preserved.

**G7 traceability:** The new `Interaction` row is the CRM write-back. DNA delta Citations should reference this new `Interaction.id` — add Citation rows linking `client_dna → new interaction` after committing.

### Implementation Checklist
Based on CLAUDE.md principles:
- [ ] Migration `0010_voice_notes.py`: add `audio_key TEXT NULL` to `interactions`
- [ ] Update `Interaction` model with `audio_key` mapped column
- [ ] Add `apply_dna_delta(session, client_id, delta)` in `loaders/dna.py` — reuse pg_insert upsert pattern from `extract_dna()`
- [ ] New router `routers/voice_writeback.py` with `POST /clients/{client_id}/voice-notes/commit`
- [ ] Inside commit: write `Interaction` row → store audio key → call `apply_dna_delta` → add Citation rows → commit
- [ ] Register router in `main.py`
- [ ] Coordinate audio_key convention with TASK-047 implementer (who does the MediaRecorder upload)

### Risk Analysis
- **Risk Level:** MEDIUM
- **Main Risks:**
  - **TASK-047 delta schema mismatch:** TASK-047 is not yet done; if its delta structure differs from what this task assumes, the commit endpoint contract breaks. Mitigation: define the `dna_delta` Pydantic model here with all fields optional; document clearly so TASK-047 aligns to it.
  - **Audio bytes not captured by TASK-046:** `useVoiceInput.ts` only exposes text transcript, not a raw audio blob. Mitigation: flag this gap to TASK-047 — it must add MediaRecorder capture. TASK-048's endpoint accepts a pre-uploaded `audio_key` (not raw bytes), keeping concerns separate.
  - **Concurrent DNA writes:** `extract_dna` and `apply_dna_delta` both upsert on `client_id`. They are safe individually (pg_insert ON CONFLICT), but if both run simultaneously the version increment is non-deterministic. Mitigation: acceptable for MVP; note in code.

### Estimated Effort
- Original: S
- Adjusted: S (confirmed — four small, focused changes; no new services or complex logic)
