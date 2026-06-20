"""DNA extraction pipeline (TASK-016, EPIC-04).

Runs a per-client LLM extraction over chronological CRM interaction notes and
produces a structured ClientDNA row + Citation rows linking every attribute back
to its source note (G2 traceability).

Seeding order: /admin/seed/crm must run before /admin/seed/dna.
"""

import uuid

from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import json_chat
from app.logging import get_logger
from app.models.citation import Citation
from app.models.derived import ClientDNA
from app.models.enums import SourceType
from app.models.source import Client, Interaction

log = get_logger(__name__)

# Tag vocabulary shared with TASK-010 (instrument tagging). Exclusions and tilts
# extracted from CRM notes must map to these tokens so DNA↔portfolio matching works.
VALID_TAGS: frozenset[str] = frozenset(
    {
        "us-tech",
        "fossil",
        "fossil-fuel",
        "deforestation-risk",
        "pharma",
        "neuro-research",
        "labour-risk",
        "luxury",
        "sustainability",
        "tech",
        "media",
        "crypto",
        "diversified",
    }
)


# ---------------------------------------------------------------------------
# LLM output schema (private — only used inside this module)
# ---------------------------------------------------------------------------


class _DNAAttribute(BaseModel):
    text: str
    tag: str | None = None
    # 1-based indices into the numbered note list supplied in the prompt.
    # Using integers avoids asking the model to reproduce UUID strings verbatim.
    source_note_indices: list[int] = []
    confidence: float = Field(default=0.8, ge=0.0, le=1.0)


class _DNAOutput(BaseModel):
    values: list[_DNAAttribute]
    exclusions: list[_DNAAttribute]
    tilts: list[_DNAAttribute]
    life_events: list[_DNAAttribute]
    promises: list[_DNAAttribute]
    business_context: str
    family_context: str
    temperament: str


# ---------------------------------------------------------------------------
# Prompt builder (private)
# ---------------------------------------------------------------------------

_VALID_TAGS_STR = ", ".join(sorted(VALID_TAGS))

_SYSTEM = f"""\
You are a CRM analyst for a private wealth management firm. Your task is to \
extract a structured client DNA from a chronological set of CRM interaction notes.

Output ONLY a valid JSON object — no markdown fences, no prose, no explanation.

Required schema:
{{
  "values": [{{"text": "...", "tag": null, "source_note_indices": [1,2], "confidence": 0.9}}],
  "exclusions": [{{"text": "...", "tag": "us-tech", "source_note_indices": [3], "confidence": 1.0}}],
  "tilts": [{{"text": "...", "tag": "luxury", "source_note_indices": [5,6], "confidence": 0.8}}],
  "life_events": [{{"text": "...", "tag": null, "source_note_indices": [7], "confidence": 0.9}}],
  "promises": [{{"text": "...", "tag": null, "source_note_indices": [8], "confidence": 1.0}}],
  "business_context": "single paragraph",
  "family_context": "single paragraph",
  "temperament": "single paragraph"
}}

Rules:
1. source_note_indices: cite ONLY the integer indices [N] provided in the notes. \
Never invent an index that does not appear in the list.
2. For exclusions and tilts the "tag" field MUST be one of: {_VALID_TAGS_STR}. \
Set tag to null only if no vocabulary token fits.
3. Confidence: 1.0 = explicitly stated by client; 0.7 = clearly implied; 0.5 = inferred.
4. Extract ALL meaningful exclusions, tilts, values, life events, and promises you find. \
Do not summarise — prefer multiple specific items over one vague one.
5. business_context, family_context, temperament: concise single paragraph each.\
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
        "Extract the client DNA."
    )
    return [
        {"role": "system", "content": _SYSTEM},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# JSONB conversion (private)
# ---------------------------------------------------------------------------


def _to_jsonb(
    attrs: list[_DNAAttribute],
    index_to_id: dict[int, uuid.UUID],
    *,
    require_tag: bool = False,
) -> list[dict]:
    result = []
    for attr in attrs:
        valid_indices = [i for i in attr.source_note_indices if i in index_to_id]
        dropped = len(attr.source_note_indices) - len(valid_indices)
        if dropped:
            log.warning("dna.invalid_note_indices", dropped=dropped, text=attr.text[:60])

        tag = attr.tag
        if tag is not None and tag not in VALID_TAGS:
            log.warning("dna.invalid_tag", tag=tag, text=attr.text[:60])
            tag = None

        result.append(
            {
                "text": attr.text,
                "tag": tag,
                "source_note_ids": [str(index_to_id[i]) for i in valid_indices],
                "confidence": attr.confidence,
            }
        )
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def extract_dna(
    session: AsyncSession,
    client_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Extract DNA for all clients (or one if client_id provided).

    Returns {client_name: 1} for each successfully extracted DNA row.
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
            log.warning("dna.no_interactions_skipping", client=client.name)
            continue

        indexed = [(i + 1, interaction) for i, interaction in enumerate(interactions)]
        index_to_id: dict[int, uuid.UUID] = {
            idx: interaction.id for idx, interaction in indexed
        }

        messages = _build_messages(client.name, client.mandate.value, indexed)
        dna_out = await json_chat(messages, _DNAOutput, max_tokens=2048)

        values_jsonb = _to_jsonb(dna_out.values, index_to_id)
        exclusions_jsonb = _to_jsonb(dna_out.exclusions, index_to_id, require_tag=True)
        tilts_jsonb = _to_jsonb(dna_out.tilts, index_to_id, require_tag=True)
        life_events_jsonb = _to_jsonb(dna_out.life_events, index_to_id)
        promises_jsonb = _to_jsonb(dna_out.promises, index_to_id)

        # Upsert ClientDNA — idempotent via unique client_id constraint
        upsert_values = dict(
            client_id=client.id,
            mandate=client.mandate,
            values=values_jsonb,
            exclusions=exclusions_jsonb,
            tilts=tilts_jsonb,
            life_events=life_events_jsonb,
            promises=promises_jsonb,
            business_context=dna_out.business_context,
            family_context=dna_out.family_context,
            temperament=dna_out.temperament,
            # style_profile intentionally omitted — TASK-017 owns that column
        )
        stmt = (
            pg_insert(ClientDNA)
            .values(**upsert_values)
            .on_conflict_do_update(
                index_elements=["client_id"],
                set_={
                    **{k: v for k, v in upsert_values.items() if k != "client_id"},
                    "version": ClientDNA.__table__.c.version + 1,
                },
            )
        )
        await session.execute(stmt)
        await session.flush()

        dna_row = await session.scalar(
            select(ClientDNA).where(ClientDNA.client_id == client.id)
        )

        # Delete-and-reload citations (idempotent)
        await session.execute(
            delete(Citation).where(
                Citation.owner_type == "client_dna",
                Citation.owner_id == dna_row.id,
            )
        )

        cited_ids: set[uuid.UUID] = set()
        for attr in (
            dna_out.values
            + dna_out.exclusions
            + dna_out.tilts
            + dna_out.life_events
            + dna_out.promises
        ):
            for idx in attr.source_note_indices:
                if idx in index_to_id:
                    cited_ids.add(index_to_id[idx])

        for interaction_id in cited_ids:
            session.add(
                Citation(
                    owner_type="client_dna",
                    owner_id=dna_row.id,
                    source_type=SourceType.CRM_NOTE,
                    source_id=interaction_id,
                )
            )

        await session.commit()
        log.info(
            "dna.client_extracted",
            client=client.name,
            notes=len(interactions),
            citations=len(cited_ids),
        )
        results[client.name] = 1

    log.info("dna.extraction_complete", clients=len(results))
    return results


# ---------------------------------------------------------------------------
# Delta apply (TASK-048 write-back)
# ---------------------------------------------------------------------------

_DELTA_KEYS: tuple[str, ...] = ("values", "exclusions", "tilts", "life_events", "promises")


async def apply_dna_delta(
    session: AsyncSession,
    client_id: uuid.UUID,
    delta: dict[str, list[dict]],
    source_interaction_id: uuid.UUID,
) -> int:
    """Append approved delta items to existing ClientDNA JSONB lists and bump version.

    Each incoming delta item gets `source_note_ids` set to the new Interaction so
    the DNA→CRM traceability (G2) carries forward. Returns the new version number.
    Tags on exclusions/tilts are validated against VALID_TAGS; unknown tags are
    cleared to null (same rule as extract_dna).
    """
    dna_row = await session.scalar(
        select(ClientDNA).where(ClientDNA.client_id == client_id)
    )
    if dna_row is None:
        raise RuntimeError(
            f"No ClientDNA for client {client_id} — run /admin/seed/dna first"
        )

    source_id_str = str(source_interaction_id)
    merged: dict[str, list[dict]] = {}

    for key in _DELTA_KEYS:
        new_items = delta.get(key) or []
        if not new_items:
            continue

        # Stamp each item with the new interaction as its source and validate tags.
        stamped = []
        for item in new_items:
            tag = item.get("tag")
            if tag is not None and tag not in VALID_TAGS:
                log.warning("dna_delta.invalid_tag", tag=tag, key=key)
                tag = None
            stamped.append(
                {
                    "text": item.get("text", ""),
                    "tag": tag,
                    "source_note_ids": [source_id_str],
                    "confidence": item.get("confidence", 0.8),
                }
            )

        existing = getattr(dna_row, key) or []
        merged[key] = existing + stamped

    if not merged:
        log.info("dna_delta.empty_delta", client_id=str(client_id))
        return dna_row.version

    set_clause: dict = {k: v for k, v in merged.items()}
    set_clause["version"] = ClientDNA.__table__.c.version + 1

    stmt = (
        pg_insert(ClientDNA)
        .values(client_id=client_id, **{k: [] for k in _DELTA_KEYS})
        .on_conflict_do_update(
            index_elements=["client_id"],
            set_=set_clause,
        )
    )
    await session.execute(stmt)
    await session.flush()

    updated = await session.scalar(
        select(ClientDNA).where(ClientDNA.client_id == client_id)
    )

    # Citation row per updated list key (one covers all items from this source)
    existing_citations = await session.execute(
        select(Citation).where(
            Citation.owner_type == "client_dna",
            Citation.owner_id == updated.id,
            Citation.source_type == SourceType.CRM_NOTE,
            Citation.source_id == source_interaction_id,
        )
    )
    if not existing_citations.scalars().first():
        session.add(
            Citation(
                owner_type="client_dna",
                owner_id=updated.id,
                source_type=SourceType.CRM_NOTE,
                source_id=source_interaction_id,
            )
        )

    log.info(
        "dna_delta.applied",
        client_id=str(client_id),
        keys=list(merged.keys()),
        new_version=updated.version,
    )
    return updated.version
