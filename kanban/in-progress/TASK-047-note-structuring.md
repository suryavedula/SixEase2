# TASK-047: Note structuring and extraction

**Status:** IN-PROGRESS · **Epic:** EPIC-11 · **Priority:** P1 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Turn a dictation/interaction into a structured CRM note (date, medium, contact, body); extract proposed DNA updates (values/promises/life events) and follow-up tasks, with sources.

## Acceptance Criteria
- [ ] structured note draft produced
- [ ] DNA updates + tasks proposed with sources
- [ ] presented as a draft for RM approval

## Dependencies
TASK-012 ✅ (IN-PROGRESS — `json_chat()` fully implemented in `backend/app/llm.py:63`)
TASK-016 ✅ (IN-PROGRESS — `apply_dna_delta()` + `VALID_TAGS` available in `backend/app/loaders/dna.py`)
TASK-046 ✅ (IN-PROGRESS — voice transcript string is the input this task structures)

## Refs
Requirements §19.1 VN2-VN4

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **`json_chat(messages, schema)` + `chat()`** (`backend/app/llm.py:63`) — the LLM primitive; handles fence-stripping, Pydantic validation, 3× retries. Import unchanged; this task is a new consumer alongside TASK-016.
- **`VALID_TAGS`** (`backend/app/loaders/dna.py:28`) — frozen set of allowed exclusion/tilt tag tokens; must be injected into the note-structure prompt to constrain DNA extraction (same E6 rule as TASK-016).
- **`apply_dna_delta()`** (`backend/app/loaders/dna.py:302`) — already handles appending approved new DNA items to `ClientDNA` + stamping citations. TASK-047's structured output feeds directly into this via TASK-048's `/commit` endpoint; TASK-047 itself never calls `apply_dna_delta`.
- **`CommitRequest` / `NoteIn` / `DnaDelta`** (`backend/app/routers/voice_writeback.py:39-58`) — the exact payload shapes TASK-048's `/commit` endpoint expects. TASK-047's `/structure` endpoint must return a superset of this (adds `proposed_tasks`) so the frontend can build the commit body from the draft.
- **`POST /clients/{id}/voice-notes/commit`** (`backend/app/routers/voice_writeback.py:108`) — TASK-048's endpoint; the frontend calls this on RM approval. TASK-047 does not modify it.
- **`Task` ORM model + `POST /clients/{id}/tasks`** (`backend/app/routers/tasks.py:121`) — task creation endpoint already exists; accepts `{title, source: "note", execution_mode: "Auto"|"Manual"}`. TASK-047 proposes task titles; frontend calls `/tasks` per accepted task on approval.
- **`classify_execution_mode(task_kind)` + `TaskKind`** (`backend/app/loaders/task_classify.py:25` + `backend/app/models/enums.py:88`) — autonomy-boundary classifier (TK3). The note-structure LLM classifies tasks as research/draft_prep/contact_client etc.; `classify_execution_mode` maps kind → Auto/Manual.
- **`useVoiceInput` hook** (`frontend/src/hooks/useVoiceInput.ts`, from TASK-046) — provides the transcript string that triggers `/note` and feeds `/structure`.
- **`InputDock.tsx`** (`frontend/src/components/shell/InputDock.tsx:76-86`) — existing `/note` stub at line 76 returns a `FallbackCard`; TASK-047 replaces this with a `VoiceNoteWidget` render, passing `transcript` and `lastClientId`.
- **`tasks.ts` API module** (`frontend/src/api/tasks.ts`) — `createTask(clientId, body)` already wraps `POST /clients/{id}/tasks`; the approval flow calls it per accepted task.
- **`SourcesFooter` widget** (`frontend/src/components/widgets/SourcesFooter.tsx`) — can be reused in `VoiceNoteWidget` to display the source note citations (G2).

### Dependencies Required
- **Backend packages:** none new — `openai`, `tenacity`, `pydantic`, `fastapi`, `sqlalchemy` all in `requirements.txt`
- **Frontend packages:** none new
- **Database migrations:** none — no new tables; `/structure` returns a draft, never writes
- **Docker services:** `ollama` (Gemma 3 12B) or Phoeniqs fallback; `postgres` (Client lookup for name context)

### Impact Assessment

#### Files to Create
- `backend/app/loaders/note_structure.py` — `structure_note(client_name, transcript) → NoteStructureOutput` (pure LLM service, no FastAPI imports)
- `frontend/src/api/notes.ts` — `postNoteStructure(clientId, transcript)` wrapping the new endpoint
- `frontend/src/components/widgets/VoiceNoteWidget.tsx` — draft review UI: editable note fields + DNA proposals + task proposals + Approve/Discard

#### Files to Modify
- `backend/app/routers/voice_writeback.py` — add `POST /clients/{client_id}/voice-notes/structure` endpoint; import `structure_note` from `loaders/note_structure`
- `frontend/src/components/shell/InputDock.tsx` — replace `/note` stub (lines 76–86) to render `VoiceNoteWidget` with `{transcript, clientId: lastClientId}`

#### Files NOT changed
- `backend/app/loaders/dna.py` — consumed read-only (`VALID_TAGS`, `apply_dna_delta`)
- `backend/app/routers/tasks.py` — task creation endpoint used as-is
- `backend/app/routers/voice_writeback.py` commit endpoint — untouched (TASK-048 owns it)
- `frontend/src/api/tasks.ts` — `createTask()` consumed as-is

#### Components Affected
- `voice_writeback.py` (HIGH) — new `/structure` endpoint added; commit endpoint unchanged
- `note_structure.py` (HIGH) — new loader; core LLM extraction logic
- `VoiceNoteWidget.tsx` (HIGH) — new UI; most complex piece; calls two backend endpoints on approval
- `InputDock.tsx` (LOW) — `/note` stub replacement only; no other behaviour changes

#### API Changes
- **New:** `POST /clients/{client_id}/voice-notes/structure`
  - Request: `{"transcript": "...", "today": "2026-06-20"}` (today supplied by client to avoid timezone drift)
  - Response: `{"note": {date, medium, client_contact, body}, "proposed_dna": [{category, text, tag, confidence}], "proposed_tasks": [{title, kind, execution_mode}]}`
  - No DB write — pure LLM draft

#### Database Changes
- None from TASK-047. The RM-approved commit (TASK-048 `/commit`) and task creation (`/tasks`) write to DB.

### Module Design

#### `backend/app/loaders/note_structure.py`

```python
# LLM output schema
class _StructuredNote(BaseModel):
    date: str | None = None          # ISO YYYY-MM-DD if mentioned; else None
    medium: str = "VoiceNote"
    client_contact: str | None = None  # person name if mentioned
    body: str                         # clean, structured note body

class _ProposedDNAItem(BaseModel):
    category: Literal["values", "exclusions", "tilts", "life_events", "promises"]
    text: str
    tag: str | None = None            # VALID_TAGS token or null
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)

class _ProposedTask(BaseModel):
    title: str
    kind: str                         # TaskKind.value string (e.g. "research", "contact_client")

class NoteStructureOutput(BaseModel):
    note: _StructuredNote
    proposed_dna: list[_ProposedDNAItem]
    proposed_tasks: list[_ProposedTask]

# Public API
async def structure_note(client_name: str, transcript: str, today: str) -> NoteStructureOutput:
    """Run LLM extraction: transcript → structured draft with DNA + task proposals."""
    # system prompt instructs: output JSON only; date = today if not found; valid tags list;
    # task kinds list (research, news_gather, draft_prep → Auto; contact_client etc. → Manual)
    # proposed_dna: only NEW information not likely already known; tag mandatory for exclusions/tilts
    ...
```

#### `POST /clients/{client_id}/voice-notes/structure` (in `voice_writeback.py`)

```python
class StructureRequest(BaseModel):
    transcript: str
    today: str | None = None   # ISO date; backend falls back to date.today() if absent

class StructureResponse(NoteStructureOutput):
    pass  # exposes the loader output directly

@router.post("/{client_id}/voice-notes/structure", response_model=StructureResponse)
async def structure_voice_note(client_id: uuid.UUID, body: StructureRequest, ...):
    # 1. Fetch client name (needed for prompt context)
    # 2. Call structure_note(client.name, body.transcript, body.today or today())
    # 3. Map each proposed_task.kind through classify_execution_mode(); attach execution_mode
    # 4. Return the draft — NO DB write (G1: RM must approve before commit)
```

#### `frontend/src/components/widgets/VoiceNoteWidget.tsx`

Three approval-gated sections:
1. **Structured note** — editable fields: date (input[date]), medium (input[text] pre-filled "VoiceNote"), client_contact (input[text]), body (textarea). RM edits before approving.
2. **DNA proposals** — one row per item: category badge + text + tag badge + confidence. Checkbox to include/exclude from delta. Defaults all checked.
3. **Task proposals** — one row per task: title + Auto/Manual badge. Checkbox. Defaults all checked.

**Approve & Commit** button (disabled until at least `body` is filled):
1. `POST /clients/{id}/voice-notes/commit` with edited note + selected DNA items → gets `interaction_id`
2. For each checked task: `POST /clients/{id}/tasks` with `{title, source: "note", execution_mode}`
3. On success: show confirmation ("Note saved, N tasks created") then hide widget

**Discard** button: clear state, hide widget; no network call.

### Implementation Checklist
Based on CLAUDE.md principles:
- [ ] Create `backend/app/loaders/note_structure.py` with `NoteStructureOutput` schema and `structure_note()` — no FastAPI imports (SOLID: pure service)
- [ ] Inject `VALID_TAGS` and `TaskKind` values into the LLM system prompt (import from `loaders/dna.py` and `models/enums.py`)
- [ ] Post-validate `tag` on returned `proposed_dna` items against `VALID_TAGS`; clear invalid to `null` (same pattern as `_to_jsonb`)
- [ ] Post-validate `kind` on `proposed_tasks` against `TaskKind` values; drop unknown kinds with a warning log
- [ ] Attach `execution_mode` to each task via `classify_execution_mode(TaskKind(kind))` inside the endpoint (not the loader)
- [ ] Add `POST /clients/{id}/voice-notes/structure` to `voice_writeback.py`; fetch client row for name context; handle 404
- [ ] `StructureRequest.today` falls back to `str(date.today())` server-side when absent
- [ ] Create `frontend/src/api/notes.ts` with `postNoteStructure(clientId, transcript, today)` → typed `StructureResponse`
- [ ] Create `frontend/src/components/widgets/VoiceNoteWidget.tsx`; three sections; all fields editable; checkbox-gated approval; loading + error states
- [ ] Reuse `SourcesFooter` for citation display in the widget (G2)
- [ ] Replace `/note` stub in `InputDock.tsx` lines 76–86; render `VoiceNoteWidget` with `clientId: lastClientId ?? ""`; if no client context show an inline hint "Select a client first with /client <name>"
- [ ] Wire `onAddSpecs([{component: "VoiceNoteWidget", props: {transcript, clientId}}])` from the `/note` resolver
- [ ] `max_tokens=1024` for `json_chat` (note structure output is smaller than full DNA extraction)
- [ ] Log `note_structure.start`, `note_structure.done` with `client_name` and `transcript_length` (not the transcript itself)
- [ ] Never write to DB inside `/structure` — draft is ephemeral until RM approves (G1)

### Risk Analysis
- **Risk Level:** MEDIUM
- **Main Risks:**
  - *LLM invents dates* — mitigation: inject `today` into the prompt as the explicit fallback; instruct model to output `null` if date is not mentioned in the transcript (not to guess).
  - *LLM proposes DNA items already in existing DNA* — mitigation: TASK-047 does not de-duplicate against stored DNA; the RM reviews and can uncheck duplicates. Full de-dup is a UX concern for a later iteration, not required for MVP.
  - *`lastClientId` is null when `/note` is invoked* — mitigation: `VoiceNoteWidget` renders a client-picker or inline hint when `clientId` is empty; the `/structure` endpoint 404s cleanly if a bad UUID is passed.
  - *TaskKind classification by the model* — mitigation: provide the complete `TaskKind` value list in the prompt; post-validate and drop unknown kinds; `classify_execution_mode` is the authoritative TK3 gate, not the LLM.
  - *Transcript too long for structured extraction* — voice dictation notes are typically < 500 tokens; `max_tokens=1024` for the response is sufficient. Monitor for unusually verbose sessions.

### Estimated Effort
- Original: M
- Adjusted: M (no change — LLM client, DNA delta, task endpoint, and voice commit are all ready; core work is one loader + one endpoint + one widget)

### Implementation Path
1. `backend/app/loaders/note_structure.py` (no deps outside `llm.py` and `enums.py`)
2. Extend `backend/app/routers/voice_writeback.py` with `/structure` endpoint
3. `frontend/src/api/notes.ts` (thin wrapper)
4. `frontend/src/components/widgets/VoiceNoteWidget.tsx` (most complex; has internal loading state)
5. Update `InputDock.tsx` `/note` stub last (touches running code; simplest change)
