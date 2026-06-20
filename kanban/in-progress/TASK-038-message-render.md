# TASK-038: LLM render in style + guardrail

**Status:** IN-PROGRESS · **Epic:** EPIC-09 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Glody Figueiredo · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
LLM renders the fact sheet in the client style profile (data-driven or values-led), citing evidence; guardrail validates that every number appears in the fact sheet and the text is draft-framed.

## Acceptance Criteria
- [ ] draft generated in chosen style
- [ ] guardrail rejects hallucinated numbers (MSG4)
- [ ] returns draft + facts_used + provenance

## Dependencies
TASK-012, TASK-017, TASK-037

## Refs
Requirements §16 MSG3/MSG4

---

## Technical Analysis (Auto-generated 2026-06-20)

### Dependency Status

All three dependencies are **fully implemented** in `kanban/in-progress/`:

- **TASK-012** (`backend/app/llm.py`) — `json_chat(messages, schema, temperature, max_tokens)` is live with Pydantic validation + 3× retries + fence-stripping. Import unchanged.
- **TASK-017** (`backend/app/loaders/style_profile.py`) — `ClientDNA.style_profile` JSONB is populated per client with `{preset, analytical_emotional, data_values, signature_phrases, …}`. The `preset` key is `"data-driven"` | `"values-led"` | `"balanced"`.
- **TASK-037** (`backend/app/loaders/fact_sheet.py`) — `assemble_fact_sheet()` creates `MessageDraft` rows with `fact_sheet JSONB` and `style = str(dna.style_profile)`. The draft is `status=DRAFT` with `draft_text=None` — TASK-038 fills that in.

### Existing Resources Found

- **`MessageDraft` ORM** (`backend/app/models/derived.py:116`) — target row. All columns for TASK-038 already exist: `draft_text Text`, `facts_used JSONB`, `provenance JSONB`, `status DraftStatus`. No migration needed.
- **`ClientDNA.style_profile`** (`derived.py:61`) — `{preset, analytical_emotional, brief_detailed, formal_warm, data_values, risk_opportunity, signature_phrases, language_formality}`. Load directly via `client_id` (more reliable than parsing `MessageDraft.style`, which is `str(dict)`).
- **`json_chat(messages, schema, temperature, max_tokens)`** (`app.llm`) — structured LLM output with retries. Import unchanged.
- **`update()` / `select()` patterns** — established by `style_profile.py` and `fact_sheet.py`. Reuse exactly.
- **`POST /admin/assemble/fact-sheet`** (`admin.py:346`) — the seeding predecessor; follow the same endpoint pattern for `POST /admin/render/message`.
- **`chat()` helper** (`app.llm`) — available for free-text generation if structured output proves unreliable for long drafts; fall back to this + manual parse if `json_chat()` times out on 2k-token output.

### MSG3/MSG5 Spec (Requirements §16)

**MSG3 — Render contract:** LLM uses ONLY the fact sheet, writes in the style profile, cites evidence inline, returns `{draft, facts_used[]}`. Low temperature (0.2) for fidelity.

**MSG4 — Guardrail:** Every number in the draft must appear in the fact sheet. Text must be draft-framed (no performance promises). Provenance map (claim → source) attached.

**MSG5 — Draft structure:**
1. Personal opening (use signature phrases / formality from style profile)
2. What happened (in their frame: data-first for data-driven; values/impact for values-led)
3. Why it matters to *you* (DNA link — reference dna_points[].value)
4. Recommendation (swap candidate or "monitor" if no proposal)
5. Reassurance (mandate unchanged — E8; `mandate_impact_unchanged=True`)
6. Their decision ("shall we discuss?")

### LLM Output Schema

```python
class _DraftOutput(BaseModel):
    draft: str               # full advisory message text
    facts_used: list[str]    # list of fact_sheet key paths the LLM cited
                             # e.g. ["numbers.current_chf", "proposal.dna_reason"]
```

The `facts_used` keys map to fact_sheet top-level keys / nested paths. The LLM is instructed to list only keys it actually used. Graceful fallback: if LLM returns empty `facts_used`, guardrail still runs on numbers.

### Guardrail Design (MSG4)

```python
import re, json

_NUMBER_RE = re.compile(r'\b\d[\d,.]*\d\b|\b\d+\b')

def _extract_numbers(text: str) -> set[str]:
    # Normalise: strip commas and trailing dots; e.g. "1,234.56" → "1234.56"
    return {m.group().replace(",", "") for m in _NUMBER_RE.finditer(text)}

def _guardrail(draft_text: str, fact_sheet: dict) -> tuple[bool, list[str]]:
    """Every number in draft must appear verbatim (after normalisation) in fact_sheet JSON."""
    fact_str = json.dumps(fact_sheet)
    fact_numbers = _extract_numbers(fact_str)
    draft_numbers = _extract_numbers(draft_text)
    hallucinated = sorted(n for n in draft_numbers if n not in fact_numbers)
    return (len(hallucinated) == 0, hallucinated)
```

Edge cases:
- **CHF 1.2M** abbreviation: guardrail will flag it — instruct the LLM to use exact numbers from the fact sheet (e.g. "1,250,000" not "1.25M").
- **Percentages from portfolio_pct**: already a float in the fact sheet — round-tripped through JSON, so "2.45" in draft matches "2.45" in `json.dumps`.
- If guardrail rejects, raise `RuntimeError` with hallucinated numbers list (admin endpoint → 409).

### Provenance Map

```python
def _build_provenance(draft_text: str, fact_sheet: dict) -> list[dict]:
    """Identify which fact_sheet leaf values appear in the draft."""
    entries = []
    for key_path, value in _flatten(fact_sheet).items():
        v = str(value) if value is not None else ""
        if v and len(v) > 3 and v in draft_text:   # skip trivially short values
            entries.append({"fact_key": key_path, "value": v, "source": "fact_sheet"})
    return entries
```

`_flatten()` is a simple recursive dict-flattener producing `"holding.issuer"` → `"Nestlé AG"` style paths.

### Module Design (`backend/app/loaders/message_render.py`)

```python
# Public API:
#   render_message_draft(session, draft_id, preset_override=None) → dict

async def render_message_draft(
    session: AsyncSession,
    draft_id: uuid.UUID,
    preset_override: str | None = None,   # "data-driven" | "values-led" | "balanced"
) -> dict:
    # 1. Load MessageDraft — raise if missing or fact_sheet is None
    # 2. Load ClientDNA for style_profile (via draft.client_id)
    #    preset = preset_override or style_profile["preset"] or "balanced"
    # 3. Build messages from fact_sheet + style_profile + preset
    # 4. json_chat(messages, _DraftOutput, temperature=0.2, max_tokens=2048)
    # 5. _guardrail(output.draft, fact_sheet) — raise RuntimeError if fails
    # 6. _build_provenance(output.draft, fact_sheet)
    # 7. UPDATE message_drafts SET draft_text=..., facts_used=..., provenance=... WHERE id=draft_id
    # 8. session.commit()
    # 9. Return {draft_id, client_id, preset, draft_text, facts_used, provenance, guardrail_passed}
```

`preset_override` allows the RM to request the non-default style (the data-driven ⇄ values-led toggle in the UI, per Requirements §17 / §16 MSG1).

### Dependencies Required

- **Backend packages:** none new — `openai`, `tenacity`, `pydantic`, `sqlalchemy`, `asyncpg`, `re` (stdlib) all present.
- **Frontend packages:** none (backend-only)
- **Database migrations:** none — `draft_text`, `facts_used`, `provenance` columns exist in `message_drafts` from migration 0001.
- **Docker services:** `postgres` + `ollama` (or Phoeniqs fallback)
- **Seeding order:** `seed/portfolio → seed/crm → seed/dna → seed/style-profile → seed/tags → seed/fit → seed/swap → seed/alerts → assemble/fact-sheet → render/message`

### Impact Assessment

#### Files to Create
- `backend/app/loaders/message_render.py` — `render_message_draft(session, draft_id, preset_override=None)`

#### Files to Modify
- `backend/app/routers/admin.py` — add `POST /admin/render/message?draft_id=<uuid>[&preset=...]` + update module docstring with TASK-038

#### Files NOT Changed
- `backend/app/models/derived.py` — schema complete; all columns exist
- `backend/app/llm.py` — consumed unchanged
- `backend/app/loaders/fact_sheet.py` — TASK-037 owns this; TASK-038 reads the draft it creates
- `backend/app/loaders/style_profile.py` — TASK-017 owns this; TASK-038 reads `ClientDNA.style_profile`

#### Components Affected
- `message_drafts.draft_text / facts_used / provenance`: **HIGH (first write)** — TASK-038 populates these columns for the first time
- Frontend message widget (TASK-040): **HIGH dependency** — will consume `MessageDraft.draft_text` + `provenance` via a to-be-created router endpoint; TASK-038 unblocks it
- `Alert.draft_ref`: **LOW** — future TASK may set `Alert.draft_ref = draft.id` to link the rendered draft back to the alert; not TASK-038's scope

#### API Changes
- **New:** `POST /admin/render/message?draft_id=<uuid>[&preset=data-driven|values-led|balanced]`
  → `{"status": "ok", "loaded": {"draft_id": str, "preset": str, "guardrail_passed": bool, "draft_text": str, "facts_used": [...], "provenance": [...]}}`

#### Database Changes
- UPDATEs `message_drafts` where `id = draft_id`: sets `draft_text`, `facts_used`, `provenance`. No schema change.

### Implementation Checklist
- [ ] Create `backend/app/loaders/message_render.py` — pure async service, no FastAPI imports
- [ ] Load `ClientDNA` directly from DB (not from `draft.style` string) to get a proper dict
- [ ] `_DraftOutput` Pydantic model: `draft: str` + `facts_used: list[str]`
- [ ] System prompt includes: MSG5 structure, style axes with anchors, "use ONLY the fact sheet", "use exact numbers — no abbreviations like 1.2M"
- [ ] User prompt passes full fact_sheet as JSON block + style_profile axes + preset label
- [ ] `json_chat()` with `temperature=0.2`, `max_tokens=2048`
- [ ] `_guardrail()`: extract normalised numbers from draft; check each against `json.dumps(fact_sheet)`; raise `RuntimeError` listing hallucinated numbers if any found
- [ ] `_build_provenance()`: flatten fact_sheet → key_path:value; match non-trivial values in draft text
- [ ] `preset_override` parameter enables the data-driven ⇄ values-led toggle
- [ ] UPDATE `message_drafts` SET `draft_text`, `facts_used`, `provenance` (status stays `draft`)
- [ ] Add `POST /admin/render/message` to `admin.py`; update module docstring with TASK-038
- [ ] Log `message_render.draft_generated`, `message_render.guardrail_passed` with structlog
- [ ] Smoke-test: call `assemble/fact-sheet` then `render/message` on Räber's draft; inspect `draft_text` for style compliance and number accuracy
- [ ] Follow SOLID: `message_render.py` has no FastAPI imports; single responsibility (render only)

### Risk Analysis
- **Risk Level:** MEDIUM
- **Main Risks:**
  - *Number abbreviation mismatch*: LLM writes "CHF 1.25M" instead of "1250000.0" → guardrail rejects. Mitigation: explicit system prompt instruction to use exact numbers from the fact sheet; include a short worked example in the prompt.
  - *Long draft exceeds max_tokens*: 2048 tokens may be tight for a structured JSON response containing a multi-paragraph draft. Mitigation: instruct the LLM to keep drafts to 3–5 short paragraphs; raise `max_tokens` to 3072 if needed (Phoeniqs supports it).
  - *`json_chat()` fence-stripping breaks on very long JSON*: the `_strip_fences` regex in `llm.py` searches `[\s\S]*` — fine for ≤4k characters. Mitigation: test with Räber's full fact sheet JSON; fall back to `chat()` + manual JSON extraction if needed.
  - *`facts_used` list hallucinated by LLM* (keys not in fact_sheet): Mitigation: validate each key against a flattened fact_sheet key set; drop unknown keys with a warning log rather than failing.
  - *`preset_override` ignored by LLM* (reverts to default style): Mitigation: include the override label prominently in both system and user messages, and add an explicit instruction: "You MUST write in [preset] style."

### Estimated Effort
- Original: M
- Adjusted: M (confirmed)
- Reason: The render prompt (MSG5 structure + style axes) is the main effort — it requires care to get the LLM to stay within the fact sheet and produce style-appropriate output. The guardrail and provenance are straightforward Python. No new DB schema, no new packages. Admin endpoint follows the established pattern exactly.
