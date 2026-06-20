# TASK-017: Communication style-profile extraction

**Status:** IN-PROGRESS · **Epic:** EPIC-04 · **Priority:** P0 · **Type:** feature · **Effort:** S · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Extract a per-client style profile along the MSG1 axes (analytical-emotional, brief-detailed, formal-warm, data-values, risk-opportunity) plus signature values and language.

## Acceptance Criteria
- [ ] style profile stored per client
- [ ] presets data-driven and values-led derivable
- [ ] used by message generation

## Dependencies
TASK-016 (**in-progress** — `extract_dna()` is implemented and registered; `client_dna` rows must exist before style profile can be written)

## Refs
Requirements §16 MSG1

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **`ClientDNA.style_profile`** (`backend/app/models/derived.py:59`) — `style_profile: Mapped[dict | None] = mapped_column(JSONB)  # MSG1 tone/frame scores` — column already in the schema from migration 0001; explicitly left `None` by TASK-016 (`dna.py:229`: `# style_profile intentionally omitted — TASK-017 owns that column`).
- **`extract_dna()`** (`backend/app/loaders/dna.py:171`) — the exact pattern to follow: session→clients→interactions→`json_chat()`→upsert→citations→commit per client.
- **`json_chat(messages, schema, max_tokens=...)`** (`backend/app/llm.py:63`) — structured LLM output with Pydantic validation + 3× retry + fence-stripping. Import unchanged.
- **`Interaction` ORM** (`backend/app/models/source.py:34`) — source notes for the extraction (already loaded, 94 rows across 4 personas).
- **`ClientDNA` ORM** (`backend/app/models/derived.py:41`) — target row; upsert via UPDATE on `client_id` unique constraint.
- **`Citation` ORM** (`backend/app/models/citation.py`) — G2 traceability; same `owner_type="client_dna"` / `SourceType.CRM_NOTE` pattern used by TASK-016.
- **`POST /admin/seed/dna`** (`backend/app/routers/admin.py:104`) — seeding order precondition; pattern for the new `/admin/seed/style-profile` endpoint.
- **`get_logger`, `get_session`, `get_settings`** — all unchanged imports.

### MSG1 Axes (from Requirements §16)

| Axis | 0.0 | 1.0 |
|---|---|---|
| `analytical_emotional` | pure emotional | pure analytical |
| `brief_detailed` | very brief | very detailed |
| `formal_warm` | very warm | very formal |
| `data_values` | values-first | data-first |
| `risk_opportunity` | risk-framed | opportunity-framed |

**Preset derivation rule** (deterministic from scores, no LLM):
- `data_values > 0.65 AND analytical_emotional > 0.65` → preset `"data-driven"`
- `data_values < 0.35 AND analytical_emotional < 0.35` → preset `"values-led"`
- else → preset `"balanced"`

**JSONB shape stored in `style_profile`:**
```json
{
  "analytical_emotional": 0.8,
  "brief_detailed": 0.6,
  "formal_warm": 0.7,
  "data_values": 0.75,
  "risk_opportunity": 0.4,
  "signature_phrases": ["based on the data...", "historically speaking..."],
  "language_formality": "formal",
  "preset": "data-driven",
  "source_note_ids": ["<uuid>", ...]
}
```

### Dependencies Required

- **Backend packages:** none new — `openai`, `tenacity`, `pydantic`, `sqlalchemy`, `asyncpg` already present
- **Database migrations:** none — `style_profile` JSONB column exists from migration 0001
- **Docker services:** `postgres`, `ollama` (Gemma 3 12B or Phoeniqs fallback)
- **Seeding order:** `POST /admin/seed/crm` → `POST /admin/seed/dna` → `POST /admin/seed/style-profile`

### Impact Assessment

#### Files to Create
- `backend/app/loaders/style_profile.py` — `extract_style_profiles(session, client_id=None) → dict[str, int]`

#### Files to Modify
- `backend/app/routers/admin.py` — add `POST /admin/seed/style-profile` + import `extract_style_profiles`

#### Files NOT changed
- `backend/app/models/derived.py` — schema complete, `style_profile` column already there
- `backend/app/loaders/dna.py` — TASK-016 owns this; TASK-017 adds a parallel loader, not a modification
- `backend/app/llm.py` — consumed unchanged

#### Components Affected
- `client_dna.style_profile`: **HIGH** (first write — this task populates the column for all 4 real clients)
- TASK-037 (message generation): **HIGH dependency** — MSG3 reads `style_profile` to set rendering tone/frame; this task unblocks it
- TASK-011 (synthetic clients): **LOW** — `load_synthetic_clients` authors `client_dna` rows directly; may need `style_profile` added to its authored payload later (not blocking)

#### API Changes
- New: `POST /admin/seed/style-profile` → `{"status": "ok", "loaded": {"Eugen Räber": 1, ...}}`; optional `?client_id=<uuid>` for single-client extraction

#### Database Changes
- UPDATEs `client_dna.style_profile` where `client_id = X` (rows already exist from TASK-016)
- Writes `Citation` rows (delete-and-reload for `owner_type="client_dna_style"` sub-type)
- No schema changes, no new migrations

### Module Design (`backend/app/loaders/style_profile.py`)

```python
# Pydantic schema — LLM output
class _StyleScores(BaseModel):
    analytical_emotional: float = Field(ge=0.0, le=1.0)  # 0=emotional, 1=analytical
    brief_detailed: float = Field(ge=0.0, le=1.0)
    formal_warm: float = Field(ge=0.0, le=1.0)           # 0=warm, 1=formal
    data_values: float = Field(ge=0.0, le=1.0)           # 0=values, 1=data
    risk_opportunity: float = Field(ge=0.0, le=1.0)      # 0=risk, 1=opportunity
    signature_phrases: list[str] = []   # up to 5 characteristic expressions
    language_formality: str             # "formal" | "informal" | "mixed"
    # source_note_indices for G2 — same integer-index trick as dna.py
    source_note_indices: list[int] = []

# Preset derivation — pure Python, not LLM
def _derive_preset(scores: _StyleScores) -> str:
    if scores.data_values > 0.65 and scores.analytical_emotional > 0.65:
        return "data-driven"
    if scores.data_values < 0.35 and scores.analytical_emotional < 0.35:
        return "values-led"
    return "balanced"

# Public API
async def extract_style_profiles(session, client_id=None) -> dict[str, int]:
    # 1. Load clients (all or one)
    # 2. Per client: load interactions ordered by date, build numbered note list
    # 3. json_chat(messages, _StyleScores, max_tokens=1024) — shorter than DNA
    # 4. _derive_preset() — deterministic, no LLM
    # 5. UPDATE client_dna SET style_profile = {...} WHERE client_id = X
    # 6. Idempotent citations: DELETE owner_type="client_dna_style" / owner_id → INSERT
    # 7. commit per client
```

Key prompt constraints:
- System: CRM communication-style analyst; score each axis with anchoring examples per axis in the prompt
- Ask model to cite note indices for the axes where evidence is strongest
- `max_tokens=1024` (scores + phrases only, much smaller than full DNA)
- `temperature=0.1` for consistency

### Implementation Checklist
- [ ] Create `backend/app/loaders/style_profile.py` with `_StyleScores` Pydantic model and `extract_style_profiles(session, client_id=None)`
- [ ] System prompt includes axis anchoring examples (e.g. "analytical: uses numbers, cites history, asks for data" vs "emotional: reacts to family events, relationship metaphors")
- [ ] Derive preset deterministically from scores in Python (`_derive_preset()`) — never ask LLM for the preset label
- [ ] `source_note_indices` in LLM output → resolve to UUIDs → write to `style_profile["source_note_ids"]` list
- [ ] Guard: if `client_dna` row does not exist for client, raise `RuntimeError` (same pattern as `dna.py:199`)
- [ ] UPDATE (not INSERT) `client_dna.style_profile` — row already exists from TASK-016
- [ ] Idempotent citations: use `owner_type="client_dna_style"` to distinguish from TASK-016 DNA citations
- [ ] Add `POST /admin/seed/style-profile` to `admin.py` following exact pattern of `seed_dna`
- [ ] Log `style_profile.client_extracted`, `style_profile.extraction_complete` with structlog
- [ ] Reuse `json_chat()` from `app.llm`; do NOT re-implement retries
- [ ] Follow SOLID: `style_profile.py` has no FastAPI imports; pure async service function

### Risk Analysis
- **Risk Level:** LOW–MEDIUM
- **Main Risks:**
  - *TASK-016 not yet committed* — `client_dna` rows may not exist if `seed/dna` hasn't run; mitigation: guard with `RuntimeError` and document seeding order clearly.
  - *LLM scores axes inconsistently across clients* — mitigation: include concrete anchoring examples per axis in the system prompt (e.g. "For `data_values`: 1.0 = client always asks for charts and numbers before deciding; 0.0 = client leads with personal values and avoids detailed numbers").
  - *`signature_phrases` hallucinated* — mitigation: instruct the model to quote only phrases found verbatim or near-verbatim in the notes.
  - *`Citation` owner_type clash with TASK-016* — mitigated by using `"client_dna_style"` sub-type instead of `"client_dna"`.

### Estimated Effort
- Original: **S**
- Adjusted: **S** (confirmed)
- Reason: The pattern is established by TASK-016 (`dna.py`), the column exists, no migration needed. This is a smaller extraction (5 float scores vs. full lists of attributes) with a shorter prompt and shorter LLM output. The preset derivation is pure Python. Main work is writing a good axis-anchoring system prompt.
