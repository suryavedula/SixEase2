"""Communication style-profile extraction (TASK-017, EPIC-04).

Runs a per-client LLM extraction over chronological CRM interaction notes and
produces a structured style_profile dict stored in client_dna.style_profile +
Citation rows (owner_type='client_dna_style') linking scores back to source notes.

Seeding order: /admin/seed/crm then /admin/seed/dna must run first.
"""

import uuid

from pydantic import BaseModel, Field
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import json_chat
from app.logging import get_logger
from app.models.citation import Citation
from app.models.derived import ClientDNA
from app.models.enums import SourceType
from app.models.source import Client, Interaction

log = get_logger(__name__)

_VALID_FORMALITY: frozenset[str] = frozenset({"formal", "informal", "mixed"})


# ---------------------------------------------------------------------------
# LLM output schema (private — only used inside this module)
# ---------------------------------------------------------------------------


class _StyleScores(BaseModel):
    analytical_emotional: float = Field(ge=0.0, le=1.0)  # 0=emotional, 1=analytical
    brief_detailed: float = Field(ge=0.0, le=1.0)         # 0=brief, 1=detailed
    formal_warm: float = Field(ge=0.0, le=1.0)             # 0=warm, 1=formal
    data_values: float = Field(ge=0.0, le=1.0)             # 0=values-first, 1=data-first
    risk_opportunity: float = Field(ge=0.0, le=1.0)        # 0=risk-framed, 1=opportunity-framed
    signature_phrases: list[str] = []
    language_formality: str = "formal"
    source_note_indices: list[int] = []  # 1-based indices into the numbered note list


# ---------------------------------------------------------------------------
# Preset derivation (pure Python, no LLM)
# ---------------------------------------------------------------------------


def _derive_preset(s: _StyleScores) -> str:
    if s.data_values > 0.65 and s.analytical_emotional > 0.65:
        return "data-driven"
    if s.data_values < 0.35 and s.analytical_emotional < 0.35:
        return "values-led"
    return "balanced"


# ---------------------------------------------------------------------------
# Prompt builder (private)
# ---------------------------------------------------------------------------

_SYSTEM = """\
You are a CRM communication-style analyst for a private wealth management firm.
Analyse these chronological CRM interaction notes and score the client's communication style.

Score each axis 0.0–1.0 using the anchors below. Output ONLY valid JSON.

Required schema:
{
  "analytical_emotional": 0.8,
  "brief_detailed": 0.6,
  "formal_warm": 0.7,
  "data_values": 0.75,
  "risk_opportunity": 0.4,
  "signature_phrases": ["phrase from notes", "another phrase"],
  "language_formality": "formal",
  "source_note_indices": [3, 7, 12]
}

Axis anchors:

analytical_emotional (0=emotional, 1=analytical):
  0.0 — Leads with feelings; reacts strongly to family/life events; uses emotional vocabulary \
("worried", "excited about my grandchildren")
  1.0 — Asks for charts and data before deciding; uses precise language; references performance \
history and benchmarks

brief_detailed (0=brief, 1=detailed):
  0.0 — Short interactions; wants summary and key takeaway only; impatient with depth
  1.0 — Asks follow-up questions; wants full breakdowns and historical context; comfortable \
with long meetings

formal_warm (0=warm, 1=formal):
  0.0 — Uses first names; personal anecdotes; warm language ("wonderful to see you"); casual
  1.0 — Formal address; precise professional vocabulary; no personal disclosure; businesslike

data_values (0=values-first, 1=data-first):
  0.0 — Driven by personal values, ESG/purpose, family legacy, community impact
  1.0 — Driven by returns, benchmarks, market data; values are secondary to performance

risk_opportunity (0=risk-framed, 1=opportunity-framed):
  0.0 — Focuses on downside protection; asks "what could go wrong"; prioritises capital preservation
  1.0 — Attracted to upside potential; comfortable with asymmetric risk; seeks growth opportunities

Rules:
1. signature_phrases: up to 5 phrases characteristic of this client, quoted as closely as \
possible from the notes. May be empty if no distinctive phrases exist.
2. language_formality: MUST be one of "formal", "informal", or "mixed".
3. source_note_indices: cite ONLY integer indices [N] provided in the notes. Never invent \
an index that does not appear in the list. These are the notes that most informed your scores.
4. Output ONLY the JSON object — no markdown fences, no prose, no explanation.\
"""


def _build_messages(
    client_name: str,
    mandate: str,
    indexed: list[tuple[int, Interaction]],
) -> list[dict]:
    note_lines = []
    for idx, interaction in indexed:
        note_text = (interaction.note or "").replace("\xa0", " ").strip()
        date_str = str(interaction.date) if interaction.date else "unknown date"
        medium = interaction.medium or "unknown medium"
        note_lines.append(f"[{idx}] {date_str} ({medium}): {note_text}")

    notes_block = "\n".join(note_lines)
    user = (
        f"Client: {client_name} (Mandate: {mandate})\n\n"
        f"CRM Notes ({len(indexed)} entries, chronological):\n{notes_block}\n\n"
        "Score the client's communication style."
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def extract_style_profiles(
    session: AsyncSession,
    client_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Extract communication style profiles for all clients (or one if client_id provided).

    Requires /admin/seed/crm and /admin/seed/dna to have run first.
    Returns {client_name: 1} for each successfully processed client.
    Commits once per client so a failure on client N does not roll back N-1.
    """
    if client_id is not None:
        clients_result = await session.execute(
            select(Client).where(Client.id == client_id)
        )
    else:
        clients_result = await session.execute(select(Client))
    clients = clients_result.scalars().all()

    results: dict[str, int] = {}

    for client in clients:
        interactions_result = await session.execute(
            select(Interaction)
            .where(Interaction.client_id == client.id)
            .order_by(Interaction.date)
        )
        interactions = interactions_result.scalars().all()

        if not interactions:
            if client_id is not None:
                raise RuntimeError(
                    f"No interactions found for '{client.name}' — run /admin/seed/crm first"
                )
            log.warning("style_profile.no_interactions_skipping", client=client.name)
            continue

        dna_row = await session.scalar(
            select(ClientDNA).where(ClientDNA.client_id == client.id)
        )
        if dna_row is None:
            if client_id is not None:
                raise RuntimeError(
                    f"No DNA row found for '{client.name}' — run /admin/seed/dna first"
                )
            log.warning("style_profile.no_dna_skipping", client=client.name)
            continue

        indexed = [(i + 1, interaction) for i, interaction in enumerate(interactions)]
        index_to_id: dict[int, uuid.UUID] = {
            idx: interaction.id for idx, interaction in indexed
        }

        messages = _build_messages(client.name, client.mandate.value, indexed)
        scores = await json_chat(messages, _StyleScores, max_tokens=512)

        valid_indices = [i for i in scores.source_note_indices if i in index_to_id]
        dropped = len(scores.source_note_indices) - len(valid_indices)
        if dropped:
            log.warning(
                "style_profile.invalid_note_indices",
                client=client.name,
                dropped=dropped,
            )

        formality = scores.language_formality
        if formality not in _VALID_FORMALITY:
            log.warning(
                "style_profile.invalid_formality",
                client=client.name,
                value=formality,
            )
            formality = "formal"

        preset = _derive_preset(scores)

        profile_dict = {
            "preset": preset,
            "analytical_emotional": scores.analytical_emotional,
            "brief_detailed": scores.brief_detailed,
            "formal_warm": scores.formal_warm,
            "data_values": scores.data_values,
            "risk_opportunity": scores.risk_opportunity,
            "signature_phrases": scores.signature_phrases,
            "language_formality": formality,
            "source_note_ids": [str(index_to_id[i]) for i in valid_indices],
        }

        await session.execute(
            update(ClientDNA)
            .where(ClientDNA.id == dna_row.id)
            .values(style_profile=profile_dict)
        )

        await session.execute(
            delete(Citation).where(
                Citation.owner_type == "client_dna_style",
                Citation.owner_id == dna_row.id,
            )
        )

        cited_ids: set[uuid.UUID] = {index_to_id[i] for i in valid_indices}
        for interaction_id in cited_ids:
            session.add(
                Citation(
                    owner_type="client_dna_style",
                    owner_id=dna_row.id,
                    source_type=SourceType.CRM_NOTE,
                    source_id=interaction_id,
                )
            )

        await session.commit()
        log.info(
            "style_profile.client_extracted",
            client=client.name,
            preset=preset,
            notes=len(interactions),
            citations=len(cited_ids),
        )
        results[client.name] = 1

    log.info("style_profile.extraction_complete", clients=len(results))
    return results
