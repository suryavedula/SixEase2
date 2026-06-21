"""MSG3/MSG4 message render + guardrail (TASK-038, EPIC-09).

Takes a MessageDraft with a populated fact_sheet (written by TASK-037), calls the
LLM to render the facts in the client's style profile (MSG3), then validates that
no numbers were hallucinated (MSG4 guardrail). Writes draft_text, facts_used, and
provenance back to the same MessageDraft row.

Seeding order: seed/style-profile → assemble/fact-sheet → render/message
"""

import json
import re
import uuid
from typing import Any

from pydantic import BaseModel
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import json_chat
from app.logging import get_logger
from app.models.derived import ClientDNA, MessageDraft

log = get_logger(__name__)

_VALID_PRESETS: frozenset[str] = frozenset({"data-driven", "values-led", "balanced"})

_NUMBER_RE = re.compile(r"\b\d[\d,.]*\d\b|\b\d+\b")


# ---------------------------------------------------------------------------
# LLM output schema (private)
# ---------------------------------------------------------------------------


class _DraftOutput(BaseModel):
    draft: str
    facts_used: list[str] = []  # fact_sheet key paths cited, e.g. ["numbers.current_chf"]


# ---------------------------------------------------------------------------
# Guardrail (MSG4) — pure function
# ---------------------------------------------------------------------------


def _extract_numbers(text: str) -> set[str]:
    return {m.group().replace(",", "") for m in _NUMBER_RE.finditer(text)}


def _guardrail(draft_text: str, fact_sheet: dict) -> tuple[bool, list[str]]:
    """Every number appearing in the draft must appear (normalised) in the fact sheet JSON."""
    fact_numbers = _extract_numbers(json.dumps(fact_sheet))
    draft_numbers = _extract_numbers(draft_text)
    hallucinated = sorted(n for n in draft_numbers if n not in fact_numbers)
    return (len(hallucinated) == 0, hallucinated)


# ---------------------------------------------------------------------------
# Provenance builder — pure function
# ---------------------------------------------------------------------------


def _flatten(d: Any, prefix: str = "") -> dict[str, Any]:
    """Recursively flatten a nested dict into dot-path key → leaf-value pairs."""
    out: dict[str, Any] = {}
    if isinstance(d, dict):
        for k, v in d.items():
            child = f"{prefix}.{k}" if prefix else k
            out.update(_flatten(v, child))
    elif isinstance(d, list):
        for i, item in enumerate(d):
            out.update(_flatten(item, f"{prefix}[{i}]"))
    else:
        out[prefix] = d
    return out


def _build_provenance(draft_text: str, fact_sheet: dict) -> list[dict]:
    entries = []
    for key_path, value in _flatten(fact_sheet).items():
        v = str(value) if value is not None else ""
        if len(v) > 3 and v in draft_text:
            entries.append({"fact_key": key_path, "value": v, "source": "fact_sheet"})
    return entries


# ---------------------------------------------------------------------------
# Prompt builder (private)
# ---------------------------------------------------------------------------

_SYSTEM_TEMPLATE = """\
You are drafting a personalised client communication for a relationship manager to \
review and send. You translate locked advisory facts into warm, accurate prose — the \
relationship manager always approves before anything reaches the client.

STYLE PRESET: {preset}

Client style profile:
  analytical_emotional: {analytical_emotional:.2f}  \
(0=emotional, 1=analytical)
  brief_detailed:       {brief_detailed:.2f}  \
(0=brief, 1=detailed)
  formal_warm:          {formal_warm:.2f}  \
(0=warm/personal, 1=formal/businesslike)
  data_values:          {data_values:.2f}  \
(0=values-first, 1=data-first)
  risk_opportunity:     {risk_opportunity:.2f}  \
(0=risk-framed, 1=opportunity-framed)
  language_formality:   {language_formality}
  signature_phrases:    {signature_phrases}

You MUST write in {preset} style:
  data-driven  — lead with numbers, performance, and evidence; keep emotional language minimal.
  values-led   — lead with personal values, DNA resonance, and purpose; numbers support the \
narrative rather than lead it.
  balanced     — blend data with personal connection; neither purely analytical nor purely \
values-focused.

DRAFT STRUCTURE (MSG5 — follow exactly in this order):
1. Personal opening that matches the client's register (formal/warm/casual).
2. What happened — the trigger event, in the client's frame (data-first or values-first).
3. Why it matters to *this client* — reference the dna_points values by name.
4. Recommendation — the swap candidate if available, or "monitor and discuss" if proposal is null.
5. Reassurance — the mandate is unchanged; this is a like-for-like replacement (E8).
6. Their decision — invite discussion ("shall we discuss?" or equivalent in their register).

HARD CONSTRAINTS:
- Use ONLY facts from the provided fact sheet. Do NOT invent any number, name, or claim.
- Use exact numbers as they appear in the fact sheet — never abbreviate \
(write 1250000.0 not 1.25M, write 2.45 not ~2.5%).
- Frame the message as a draft for the RM to review — never promise outcomes \
(no "this will return X%").
- Keep the draft to 3–5 short paragraphs.

OUTPUT FORMAT — return ONLY this JSON object, no markdown fences, no prose:
{{
  "draft": "<full message text>",
  "facts_used": ["<fact_sheet key path>", ...]
}}

facts_used must list only the key paths you actually referenced, \
e.g. ["numbers.current_chf", "proposal.dna_reason", "dna_points[0].value"].
If a key path does not exist in the fact sheet, omit it.\
"""


def _build_messages(
    fact_sheet: dict,
    style_profile: dict | None,
    preset: str,
) -> list[dict]:
    sp = style_profile or {}
    system = _SYSTEM_TEMPLATE.format(
        preset=preset,
        analytical_emotional=sp.get("analytical_emotional", 0.5),
        brief_detailed=sp.get("brief_detailed", 0.5),
        formal_warm=sp.get("formal_warm", 0.5),
        data_values=sp.get("data_values", 0.5),
        risk_opportunity=sp.get("risk_opportunity", 0.5),
        language_formality=sp.get("language_formality", "formal"),
        signature_phrases=", ".join(f'"{p}"' for p in sp.get("signature_phrases", [])) or "none",
    )
    user = (
        "Fact sheet (use ONLY these facts — treat every field as locked):\n\n"
        f"{json.dumps(fact_sheet, indent=2, default=str)}\n\n"
        "Draft the advisory message now."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def render_message_draft(
    session: AsyncSession,
    draft_id: uuid.UUID,
    preset_override: str | None = None,
) -> dict:
    """Render a MessageDraft's fact_sheet into styled prose via LLM (MSG3) and validate (MSG4).

    preset_override enables the data-driven ⇄ values-led UI toggle.
    Raises RuntimeError if prerequisites are missing or the guardrail rejects the output.
    Returns {draft_id, client_id, preset, draft_text, facts_used, provenance, guardrail_passed}.
    """
    draft = await session.scalar(select(MessageDraft).where(MessageDraft.id == draft_id))
    if draft is None:
        raise RuntimeError(f"MessageDraft {draft_id} not found")
    if draft.fact_sheet is None:
        raise RuntimeError(
            f"Draft {draft_id} has no fact_sheet — run /admin/assemble/fact-sheet first"
        )

    dna = await session.scalar(
        select(ClientDNA).where(ClientDNA.client_id == draft.client_id)
    )
    style_profile: dict | None = dna.style_profile if dna else None

    if preset_override is not None and preset_override not in _VALID_PRESETS:
        raise RuntimeError(
            f"Invalid preset '{preset_override}' — must be one of {sorted(_VALID_PRESETS)}"
        )
    preset = preset_override or (style_profile or {}).get("preset", "balanced")

    messages = _build_messages(draft.fact_sheet, style_profile, preset)
    output = await json_chat(messages, _DraftOutput, temperature=0.2, max_tokens=2048)

    ok, hallucinated = _guardrail(output.draft, draft.fact_sheet)
    if not ok:
        raise RuntimeError(
            f"MSG4 guardrail: draft contains numbers not found in fact sheet: {hallucinated}"
        )

    # Drop any facts_used keys that don't appear in the flattened fact_sheet
    valid_keys = set(_flatten(draft.fact_sheet).keys())
    clean_facts_used = [k for k in output.facts_used if k in valid_keys]
    dropped = len(output.facts_used) - len(clean_facts_used)
    if dropped:
        log.warning(
            "message_render.facts_used_invalid_keys",
            draft_id=str(draft_id),
            dropped=dropped,
        )

    provenance = _build_provenance(output.draft, draft.fact_sheet)

    await session.execute(
        update(MessageDraft)
        .where(MessageDraft.id == draft_id)
        .values(
            draft_text=output.draft,
            facts_used=clean_facts_used,
            provenance=provenance,
        )
    )
    await session.commit()

    log.info(
        "message_render.draft_generated",
        draft_id=str(draft_id),
        client_id=str(draft.client_id),
        preset=preset,
        guardrail_passed=True,
        provenance_entries=len(provenance),
    )

    return {
        "draft_id": str(draft_id),
        "client_id": str(draft.client_id),
        "preset": preset,
        "draft_text": output.draft,
        "facts_used": clean_facts_used,
        "provenance": provenance,
        "guardrail_passed": True,
    }
