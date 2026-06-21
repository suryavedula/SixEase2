"""Note structuring pipeline (TASK-047, EPIC-11).

Takes a raw dictation transcript and extracts a structured CRM note draft,
proposed DNA updates, and proposed follow-up tasks — all returned as a draft
for RM review. Never writes to the database (G1).

Public API:
    structure_note(client_name, transcript, today) → NoteStructureOutput
"""

from datetime import datetime, timedelta
from typing import Literal

from pydantic import BaseModel, Field

from app.llm import json_chat
from app.logging import get_logger
from app.loaders.dna import VALID_TAGS
from app.models.enums import TaskKind

log = get_logger(__name__)

_VALID_TAGS_STR = ", ".join(sorted(VALID_TAGS))
_TASK_KINDS_STR = ", ".join(k.value for k in TaskKind)


# ---------------------------------------------------------------------------
# LLM output schema
# ---------------------------------------------------------------------------


class _StructuredNote(BaseModel):
    date: str | None = None
    medium: str = "VoiceNote"
    client_contact: str | None = None
    body: str


class _ProposedDNAItem(BaseModel):
    category: Literal["values", "exclusions", "tilts", "life_events", "promises"]
    text: str
    tag: str | None = None
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class _ProposedTask(BaseModel):
    title: str
    kind: str


class _ProposedEvent(BaseModel):
    title: str
    start: str  # local ISO-8601 datetime "YYYY-MM-DDTHH:MM:SS"
    end: str | None = None  # filled to start+1h by validation when absent
    notes: str | None = None


class NoteStructureOutput(BaseModel):
    note: _StructuredNote
    proposed_dna: list[_ProposedDNAItem]
    proposed_tasks: list[_ProposedTask]
    proposed_events: list[_ProposedEvent] = []


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

_SYSTEM = f"""\
You are a CRM note analyst for a private wealth management firm. An RM has \
dictated a note about a client interaction. Your job is to:

1. Structure the raw transcript into a clean CRM note.
2. Identify genuinely NEW client DNA insights (values, exclusions, tilts, \
life events, promises) that would not already be in a typical client profile.
3. Extract concrete follow-up tasks the RM must act on.

Output ONLY a valid JSON object — no markdown fences, no prose, no explanation.

Required schema:
{{
  "note": {{
    "date": "YYYY-MM-DD or null",
    "medium": "VoiceNote",
    "client_contact": "name or null",
    "body": "clean structured prose summary"
  }},
  "proposed_dna": [
    {{"category": "values|exclusions|tilts|life_events|promises",
      "text": "...", "tag": "token or null", "confidence": 0.9}}
  ],
  "proposed_tasks": [
    {{"title": "...", "kind": "research|draft_prep|contact_client|..."}}
  ],
  "proposed_events": [
    {{"title": "...", "start": "YYYY-MM-DDTHH:MM:SS", "end": "YYYY-MM-DDTHH:MM:SS or null", "notes": "... or null"}}
  ]
}}

Rules:
1. note.date: extract ONLY if a date is explicitly stated or clearly implied \
(e.g. "yesterday", "last Tuesday"). Use today's date (given in the user message) \
as reference. If uncertain, use null — never guess.
2. note.body: write clean structured prose. Do NOT reproduce the transcript \
verbatim; summarise what happened and what was agreed.
3. note.client_contact: extract the name of the person the RM met, if mentioned. null otherwise.
4. proposed_dna: only NEW insights not likely already captured in a standard \
profile. Do not propose obvious or generic items. Use [] if nothing fresh.
   - For exclusions and tilts, tag MUST be one of: {_VALID_TAGS_STR}. \
Set tag to null only when no vocabulary token fits.
   - confidence: 1.0 = client explicitly stated it; 0.7 = clearly implied; 0.5 = inferred.
5. proposed_tasks.kind MUST be one of: {_TASK_KINDS_STR}. \
Use "research" or "draft_prep" for internal tasks; \
"contact_client" or "send_message" for outward actions.
6. proposed_events: extract ONLY when the note explicitly schedules a meeting, \
call, or follow-up at a specific time/date (e.g. "call him Tuesday at 3pm", \
"lunch on the 25th"). Resolve relative dates against today's date. start/end as \
local "YYYY-MM-DDTHH:MM:SS". If a date is given but no time, use 09:00 and leave \
end null. If nothing is scheduled, use []. Never invent an event.
7. All lists may be []. Do not invent tasks, DNA items, or events that are not \
grounded in the transcript.\
"""


def _build_messages(client_name: str, transcript: str, today: str) -> list[dict]:
    # NB: _SYSTEM is an f-string, so its JSON-schema braces are already literal.
    # Do NOT call .format() on it — today is supplied via the user message below.
    system = _SYSTEM
    user = (
        f"Client: {client_name}\n"
        f"Today's date: {today}\n\n"
        f"Raw transcript:\n{transcript}\n\n"
        "Structure this note and extract DNA updates and follow-up tasks."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# Post-validation helpers
# ---------------------------------------------------------------------------


def _validated_dna(items: list[_ProposedDNAItem]) -> list[_ProposedDNAItem]:
    result = []
    for item in items:
        tag = item.tag
        if tag is not None and tag not in VALID_TAGS:
            log.warning("note_structure.invalid_tag", tag=tag, text=item.text[:60])
            tag = None
        result.append(item.model_copy(update={"tag": tag}))
    return result


def _validated_tasks(items: list[_ProposedTask]) -> list[_ProposedTask]:
    valid_kinds = {k.value for k in TaskKind}
    result = []
    for item in items:
        if item.kind not in valid_kinds:
            log.warning("note_structure.invalid_task_kind", kind=item.kind, title=item.title[:60])
            continue
        result.append(item)
    return result


def _validated_events(items: list[_ProposedEvent]) -> list[_ProposedEvent]:
    """Drop events with an unparseable start; default a missing end to start + 1h."""
    result = []
    for item in items:
        try:
            start_dt = datetime.fromisoformat(item.start)
        except (ValueError, TypeError):
            log.warning("note_structure.invalid_event_start", start=item.start, title=item.title[:60])
            continue
        end = item.end
        if end:
            try:
                datetime.fromisoformat(end)
            except (ValueError, TypeError):
                end = None
        if not end:
            end = (start_dt + timedelta(hours=1)).isoformat(timespec="seconds")
        result.append(item.model_copy(update={"start": start_dt.isoformat(timespec="seconds"), "end": end}))
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def structure_note(
    client_name: str,
    transcript: str,
    today: str,
) -> NoteStructureOutput:
    """Extract a structured note draft + DNA + task proposals from a raw transcript.

    Never reads or writes the database — callers own persistence (G1).
    """
    log.info(
        "note_structure.start",
        client_name=client_name,
        transcript_len=len(transcript),
    )
    messages = _build_messages(client_name, transcript, today)
    result = await json_chat(messages, NoteStructureOutput, max_tokens=1024)

    validated = NoteStructureOutput(
        note=result.note,
        proposed_dna=_validated_dna(result.proposed_dna),
        proposed_tasks=_validated_tasks(result.proposed_tasks),
        proposed_events=_validated_events(result.proposed_events),
    )

    log.info(
        "note_structure.done",
        client_name=client_name,
        dna_proposals=len(validated.proposed_dna),
        task_proposals=len(validated.proposed_tasks),
        event_proposals=len(validated.proposed_events),
    )
    return validated
