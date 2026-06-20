# TASK-016: DNA extraction pipeline

**Status:** IN-PROGRESS · **Epic:** EPIC-04 · **Priority:** P0 · **Type:** feature · **Effort:** L · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
LLM pipeline over a client notes history producing structured DNA: values, hard exclusions, soft tilts, business/family context, temperament, life events, promises; every attribute linked to its source note(s).

## Acceptance Criteria
- [ ] DNA produced for all four personas
- [ ] exclusions/tilts map to tag vocabulary (E6)
- [ ] each attribute cites source note id (G2)

## Dependencies
TASK-009 (**done** — interactions table populated, 94 notes across 4 personas)
TASK-010 (**in-progress** — tag vocabulary fully documented; code not yet merged but vocabulary is stable and used here)
TASK-012 (**done** — `json_chat()` implemented with fence-stripping + tenacity retries)

## Refs
Requirements UC-1, §11 E6

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found

- **`ClientDNA` ORM model** (`backend/app/models/derived.py:41`) — table already exists from migration 0001. All target columns present: `client_id` (unique FK), `mandate`, `values`, `exclusions`, `tilts`, `life_events`, `promises`, `style_profile`, `business_context`, `family_context`, `temperament` — TASK-016 writes all except `style_profile` (owned by TASK-017).
- **`Citation` ORM model** (`backend/app/models/citation.py:22`) — polymorphic source-link table already exists. Owner `"client_dna"` + `SourceType.CRM_NOTE` is the pattern for G2 compliance.
- **`SourceType.CRM_NOTE`** (`backend/app/models/enums.py:81`) — enum value for citation source type, ready to use.
- **`Interaction` ORM model** (`backend/app/models/source.py:34`) — `id`, `client_id`, `date`, `medium`, `note` columns; 94 rows already loaded (TASK-009).
- **`Client` ORM model** (`backend/app/models/source.py:22`) — `id`, `name`, `mandate`.
- **`json_chat(messages, schema)` + `chat()`** (`backend/app/llm.py:63`) — fully implemented async LLM call with Pydantic validation + tenacity retries. TASK-016 is its first production consumer. Import directly; no modification needed.
- **`get_session` / `AsyncSession`** (`backend/app/db.py`) — session dependency.
- **`get_logger`** (`backend/app/logging.py`) — structured logging pattern.
- **Admin router pattern** (`backend/app/routers/admin.py`) — `POST /admin/seed/dna` follows the exact same structure as the three existing seed endpoints.
- **Tag vocabulary** (TASK-010 task file §Tag Vocabulary) — the `exclusions`/`tilts` list items must use tag strings from this vocabulary: `us-tech`, `fossil`, `fossil-fuel`, `deforestation-risk`, `pharma`, `neuro-research`, `labour-risk`, `luxury`, `sustainability`, `tech`, `media`, `crypto`.

### Data facts (TASK-009 + §10.1)

| Client | Mandate | Note count | \xa0 note |
|---|---|---|---|
| Eugen Räber | DEFENSIVE | 20 | last row has `\xa0` — whitespace-normalize before LLM |
| Hubertus Schneider | BALANCED | 26 | — |
| Marius Huber | BALANCED | 20 | — |
| Julian Ammann | GROWTH | 28 | — |

Context window per client: ~25 notes × ~100 words = ~2,500 tokens per prompt. Comfortably fits one LLM call per client.

### Expected DNA output per persona (from §12 archetypes + CRM content)

| Client | Exclusions | Tilts | Key life events / promises to surface |
|---|---|---|---|
| Räber | `us-tech` | Swiss/EU quality | capital preservation, no US concentration |
| Schneider | `pharma` | `neuro-research` | family Parkinson's connection, neuro funding red line |
| Huber | `fossil`, `fossil-fuel`, `deforestation-risk` | `sustainability` | sustainable agriculture, ESG commitment |
| Ammann | `labour-risk` | `luxury` | corporate reputation focus, premium brand tilts |

### Dependencies Required

- **Backend packages:** none new — `openai`, `tenacity`, `pydantic`, `sqlalchemy`, `asyncpg` already in `requirements.txt` (TASK-012 added them)
- **Database migrations:** none — `client_dna` and `citations` tables exist from migration 0001
- **Docker services:** `postgres` (running), `ollama` (running for Gemma 3 12B or Phoeniqs fallback)
- **Seeding order:** `POST /admin/seed/crm` must run before `POST /admin/seed/dna` (interactions must exist)

### Impact Assessment

#### Files to Create
- `backend/app/loaders/dna.py` — `extract_dna(session, client_id=None) → dict[str, int]` pipeline

#### Files to Modify
- `backend/app/routers/admin.py` — add `POST /admin/seed/dna` endpoint + import `extract_dna`

#### Files NOT changed
- `backend/app/models/derived.py` — `ClientDNA` schema is complete; `style_profile` left null (TASK-017)
- `backend/app/models/citation.py` — Citation table used as-is
- `backend/app/llm.py` — consumed unchanged

#### Components Affected
- `client_dna` table: **HIGH** (first write — TASK-016 creates all 4 real client rows)
- `citations` table: **HIGH** (first write — citation rows linking each DNA attribute to its source interaction)
- TASK-017 (style-profile): **LOW dependency** — writes `style_profile` column; TASK-016 leaves it null, no conflict
- TASK-020 (fit scorer): **HIGH dependency** — reads `client_dna.exclusions` + `client_dna.tilts`; blocked until TASK-016 runs
- TASK-021 (swap engine): **HIGH dependency** — exclusion tags filter the swap universe (E6)
- TASK-028 (news matching): **MEDIUM dependency** — uses DNA themes/values for thematic query generation (N2)
- TASK-011 (synthetic clients): **MEDIUM** — `load_synthetic_clients` in `app/loaders/synthetic.py` may pre-author DNA for synthetic personas; TASK-016 handles real clients only

#### API Changes
- New: `POST /admin/seed/dna` → `{"status": "ok", "loaded": {"Eugen Räber": 1, ...}}`; optional `?client_id=<uuid>` to extract for one client
- No changes to existing endpoints

#### Database Changes
- Writes to `client_dna` (upsert by `client_id` unique constraint — idempotent)
- Writes to `citations` (delete-and-reload per `client_dna` owner — idempotent)
- No schema changes

### Module Design (`backend/app/loaders/dna.py`)

```python
# Public API:
#   extract_dna(session, client_id=None) → dict[str, int]
#     Runs extraction for all 4 clients (or just one if client_id given).
#     Returns {client_name: 1} for each successfully extracted DNA row.

# Pydantic schemas for LLM structured output:
class DNAAttribute(BaseModel):
    text: str                        # human-readable attribute description
    tag: str | None = None           # tag-vocabulary token (E6) — for exclusions/tilts
    source_note_ids: list[str]       # interaction UUIDs cited (G2)
    confidence: float = Field(ge=0.0, le=1.0)

class DNAOutput(BaseModel):
    values: list[DNAAttribute]
    exclusions: list[DNAAttribute]   # hard red lines — must include tag
    tilts: list[DNAAttribute]        # soft preferences — must include tag
    life_events: list[DNAAttribute]
    promises: list[DNAAttribute]
    business_context: str
    family_context: str
    temperament: str

# Pipeline per client:
# 1. SELECT interactions WHERE client_id = X ORDER BY date
# 2. Normalise whitespace (\xa0 → space; strip); build numbered note list with UUIDs
# 3. Build system + user messages: system sets role (CRM analyst), user injects notes
# 4. json_chat(messages, DNAOutput, max_tokens=2048)
# 5. Upsert ClientDNA row (SELECT → INSERT or UPDATE via unique client_id constraint)
# 6. DELETE citations WHERE owner_type='client_dna' AND owner_id=dna.id
# 7. INSERT Citation rows for every source_note_id in every attribute list
# 8. Single commit per client (not one big commit) so partial failure is recoverable
```

Key LLM prompt constraints (baked into the system message):
- Output ONLY the JSON object matching the schema
- For exclusions and tilts, `tag` MUST be one of the known vocabulary tokens
- `source_note_ids` MUST be drawn from the note UUIDs provided in the context — never invent IDs
- Include `confidence` 0.0–1.0 based on how explicit vs. inferred the attribute is

### Implementation Checklist
- [ ] Create `backend/app/loaders/dna.py` with `DNAAttribute`, `DNAOutput` Pydantic models and `extract_dna(session, client_id=None)`
- [ ] Whitespace-normalize interaction notes (`str.replace('\xa0', ' ').strip()`) before building prompt
- [ ] System prompt explicitly lists the allowed tag vocabulary tokens for exclusions/tilts (E6 constraint)
- [ ] Prompt includes note UUIDs and instructs model to cite only provided IDs (G2 constraint)
- [ ] After `json_chat`, validate that all `source_note_ids` in the output exist in the provided interaction set; drop invalid IDs rather than failing
- [ ] Upsert `ClientDNA` using `SELECT + (INSERT or UPDATE)` on unique `client_id` index
- [ ] Idempotent citations: DELETE all citations for `owner_type="client_dna"` / `owner_id` before re-inserting
- [ ] `style_profile` column explicitly left `None` (TASK-017 owns it)
- [ ] Add `POST /admin/seed/dna` to `admin.py` following exact pattern of `seed_tags`
- [ ] Log `dna.client_extracted`, `dna.extraction_complete` with structlog
- [ ] `max_tokens=2048` in `json_chat` call (DNA output is larger than typical LLM responses)
- [ ] Reuse `json_chat()` from `app.llm`; do NOT re-implement fence-stripping or retries
- [ ] Follow SOLID: `dna.py` has no FastAPI imports; pure async service function

### Risk Analysis
- **Risk Level:** MEDIUM
- **Main Risks:**
  - *LLM hallucinates note UUIDs* — mitigation: post-process output to discard any `source_note_id` not in the interaction set; log discarded IDs as a warning.
  - *Tag vocabulary mismatch* — TASK-010 not yet code-complete; mitigation: embed tag vocabulary string list directly in the prompt and the `DNAAttribute` model (the list is stable from TASK-010 analysis). Update if TASK-010 adds tags.
  - *Weak model fails JSON schema* — mitigation: `json_chat()` already retries 3× with error feedback; `max_tokens=2048` to avoid truncated JSON.
  - *Räber `\xa0` non-breaking space* — mitigation: explicit whitespace normalize step before building notes context.
  - *Context too long for small Ollama model* — 94 notes split into 4 client calls (~25 notes each, ~2.5k tokens); safe for Gemma 3 12B (128k context). Monitor for multi-note personas with very long notes.
  - *Seeding order not enforced* — if `seed/crm` hasn't run, `SELECT interactions` returns empty; mitigation: raise `RuntimeError` if no interactions found for a client, same as `load_tags` pattern.

### Estimated Effort
- Original: **L**
- Adjusted: **M–L**
- Reason: LLM client (`json_chat`), DB models (`ClientDNA`, `Citation`), loader pattern (`load_crm`), and tag vocabulary are all already built. The core work is authoring the extraction prompt, the Pydantic schemas, the upsert/citation logic, and the endpoint — nothing needs to be invented from scratch. The main complexity is prompt engineering and post-validation of note IDs.
