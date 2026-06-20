# TASK-018: DNA storage and read API

**Status:** IN-PROGRESS · **Epic:** EPIC-04 · **Priority:** P0 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Persist ClientDNA and expose read endpoints with source links for traceability and UI rendering.

## Acceptance Criteria
- [ ] GET client DNA returns structured profile + sources
- [ ] versioned so updates are tracked (UC-18)
- [ ] feeds widgets and engine

## Dependencies
TASK-004, TASK-016

## Refs
Requirements §18.1, G2

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **`ClientDNA` ORM model** — `backend/app/models/derived.py:41`
  All columns already exist (`values`, `exclusions`, `tilts`, `life_events`, `promises`,
  `style_profile`, `business_context`, `family_context`, `temperament`). **Missing:** `version` INTEGER.
- **`extract_dna()` loader** — `backend/app/loaders/dna.py`
  Fully implemented. Populates `client_dna` via upsert + writes `Citation` rows linking every
  DNA attribute back to its source `Interaction`. **Missing:** version increment on upsert.
- **`/admin/seed/dna` admin endpoint** — `backend/app/routers/admin.py:104`
  Triggers extraction. Already wired into `main.py`. No changes needed.
- **`Citation` model** — `backend/app/models/citation.py`
  Polymorphic evidence table. For DNA rows, `owner_type = "client_dna"`, `owner_id = dna.id`,
  `source_type = CRM_NOTE`, `source_id = interaction.id`. Indexes on `(owner_type, owner_id)`.
- **`Interaction` model** — `backend/app/models/source.py:34`
  Has `date`, `medium`, `note`, `client_id`. These are the source nodes to be hydrated as `sources[]`.
- **`Client` model** — `backend/app/models/source.py:22` — provides `client_name` + `mandate`.
- **`get_session` dependency** — `backend/app/db.py:37` — standard async session injection.
- **Router pattern to follow** — `backend/app/routers/similarity.py` — Pydantic request/response
  models, `APIRouter`, `Depends(get_session)`.
- **Initial schema migration** — `backend/migrations/versions/0001_initial_schema.py`
  `client_dna` table exists, **no `version` column**.
- **Latest migration** — `0003_cio_tags.py` — new migration will be `0004`.

### Dependencies Required

- Frontend packages: none new
- Backend packages: none new (SQLAlchemy, FastAPI, Pydantic all present)
- Database migrations: `0004_dna_version.py` — adds `version INTEGER NOT NULL DEFAULT 1` to `client_dna`
- Docker services: postgres (already running)

### Impact Assessment

#### Files to Create
- `backend/app/routers/dna.py`: new router with `GET /clients/{client_id}/dna`
- `backend/migrations/versions/0004_dna_version.py`: add `version` column

#### Files to Modify
- `backend/app/main.py`: register `dna` router (one `include_router` call)
- `backend/app/models/derived.py`: add `version: Mapped[int]` field to `ClientDNA`
- `backend/app/loaders/dna.py`: increment `version` on conflict in `on_conflict_do_update`

#### Components Affected
- `ClientDNA` ORM model: LOW — additive column
- `extract_dna()` loader: LOW — one extra key in `set_` dict
- `main.py`: LOW — one extra `include_router` call
- No existing endpoints are modified or broken

#### API Changes
- **NEW** `GET /clients/{client_id}/dna` → `DNAResponse` (structured profile + hydrated sources)
- All existing endpoints unchanged

#### Database Changes
- `client_dna` table: add `version INTEGER NOT NULL DEFAULT 1`
- On each DNA re-extraction the version auto-increments via `version = client_dna.version + 1`
- No history table needed for Effort-S scope (UC-18 "updates are tracked" = version counter)

### Response Contract

```json
{
  "id": "uuid",
  "client_id": "uuid",
  "client_name": "Räber",
  "mandate": "BALANCED",
  "version": 1,
  "values":      [{"text": "...", "tag": null,    "source_note_ids": ["uuid"], "confidence": 0.9}],
  "exclusions":  [{"text": "...", "tag": "us-tech","source_note_ids": ["uuid"], "confidence": 1.0}],
  "tilts":       [{"text": "...", "tag": "luxury", "source_note_ids": ["uuid"], "confidence": 0.8}],
  "life_events": [{"text": "...", "tag": null,    "source_note_ids": ["uuid"], "confidence": 0.9}],
  "promises":    [{"text": "...", "tag": null,    "source_note_ids": ["uuid"], "confidence": 1.0}],
  "style_profile": null,
  "business_context": "...",
  "family_context": "...",
  "temperament": "...",
  "sources": [
    {
      "id": "uuid",
      "date": "2024-01-15",
      "medium": "Phone",
      "note": "Client mentioned..."
    }
  ],
  "created_at": "2026-06-20T10:00:00Z",
  "updated_at": "2026-06-20T10:00:00Z"
}
```

`sources` is the de-duplicated list of `Interaction` rows cited by any `Citation` for this DNA row.
Each attribute's `source_note_ids` array resolves back into `sources[]` by `id` — clients can
cross-reference without re-fetching.

### Implementation Checklist
- [ ] Migration `0004_dna_version.py` — `ALTER TABLE client_dna ADD COLUMN version INT NOT NULL DEFAULT 1`
- [ ] `ClientDNA` model — add `version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)`
- [ ] `extract_dna()` loader — add `version = ClientDNA.version + 1` to `set_` in `on_conflict_do_update`
- [ ] `backend/app/routers/dna.py` — `GET /clients/{client_id}/dna`; join DNA + Client + Citations + Interactions
- [ ] Register router in `main.py`: `app.include_router(dna.router)`
- [ ] Return 404 if `client_id` has no DNA row yet (with message "Run /admin/seed/dna first")
- [ ] Follow existing patterns: Pydantic response model, `Depends(get_session)`, structlog logging

### Risk Analysis
- **Risk Level**: LOW
- **Main Risks**:
  - Migration on existing DB with data: safe — DEFAULT 1 handles existing rows without backfill
  - `version + 1` in upsert's `set_` dict requires referencing the table column, not a Python value:
    use `ClientDNA.__table__.c.version + 1` in the conflict handler (mitigation: test with seed endpoint)

### Estimated Effort
- Original: S
- Adjusted: S
- Reason: all plumbing exists; purely additive — new column, new router, 3 small file edits
