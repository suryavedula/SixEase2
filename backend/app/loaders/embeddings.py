"""Embedding generation and pgvector upsert (TASK-015, EPIC-03).

Calls the Ollama embedding endpoint (OpenAI-compatible /v1/embeddings) via the
existing AsyncOpenAI singleton and writes results into the `embeddings` table.
Idempotent: deletes the existing row for each owner before inserting the new one.

Owner types:
  "interaction" — CRM note (Interaction.note)
  "client_dna"  — flattened ClientDNA attributes
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.llm import get_client
from app.logging import get_logger
from app.models.derived import ClientDNA
from app.models.embedding import Embedding
from app.models.source import Interaction

log = get_logger(__name__)
settings = get_settings()

_BATCH_SIZE = 32  # safe upper bound for Ollama single-request embedding


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts via the Ollama /v1/embeddings endpoint.

    Reuses the AsyncOpenAI singleton from app.llm — no second client needed.
    """
    client = get_client()
    response = await client.embeddings.create(
        model=settings.ollama_embed_model,
        input=texts,
    )
    return [item.embedding for item in response.data]


async def _upsert_embedding(
    session: AsyncSession,
    owner_type: str,
    owner_id: uuid.UUID,
    vector: list[float],
) -> None:
    """Replace any existing embedding for this owner with a freshly computed one."""
    await session.execute(
        delete(Embedding).where(
            Embedding.owner_type == owner_type,
            Embedding.owner_id == owner_id,
        )
    )
    session.add(
        Embedding(
            owner_type=owner_type,
            owner_id=owner_id,
            model=settings.ollama_embed_model,
            vector=vector,
        )
    )


async def seed_interaction_embeddings(session: AsyncSession) -> int:
    """Embed all CRM notes (Interaction.note IS NOT NULL) into the embeddings table.

    Returns the number of embeddings written. Commits a single transaction.
    """
    result = await session.execute(
        select(Interaction).where(Interaction.note.isnot(None))
    )
    interactions = result.scalars().all()

    count = 0
    for i in range(0, len(interactions), _BATCH_SIZE):
        batch = interactions[i : i + _BATCH_SIZE]
        texts = [row.note for row in batch]
        vectors = await embed_texts(texts)
        for row, vec in zip(batch, vectors):
            await _upsert_embedding(session, "interaction", row.id, vec)
        count += len(batch)
        log.info("embeddings.interaction_batch", offset=i, batch_size=len(batch), total_so_far=count)

    await session.commit()
    log.info("embeddings.interactions_done", total=count)
    return count


async def seed_dna_embeddings(session: AsyncSession) -> int:
    """Embed all ClientDNA rows into the embeddings table.

    Gracefully returns 0 if no DNA rows exist yet (populated by TASK-016/017).
    Commits a single transaction.
    """
    result = await session.execute(select(ClientDNA))
    dna_rows = result.scalars().all()

    if not dna_rows:
        log.info("embeddings.dna_skipped", reason="no ClientDNA rows found")
        return 0

    count = 0
    for i in range(0, len(dna_rows), _BATCH_SIZE):
        batch = dna_rows[i : i + _BATCH_SIZE]
        texts = [_dna_to_text(row) for row in batch]
        vectors = await embed_texts(texts)
        for row, vec in zip(batch, vectors):
            await _upsert_embedding(session, "client_dna", row.id, vec)
        count += len(batch)
        log.info("embeddings.dna_batch", offset=i, batch_size=len(batch), total_so_far=count)

    await session.commit()
    log.info("embeddings.dna_done", total=count)
    return count


def _dna_to_text(dna: ClientDNA) -> str:
    """Flatten a ClientDNA row into a single embeddable text string.

    Each JSONB list field is serialised as labelled phrases so the embedding
    captures semantic meaning rather than raw JSON structure.
    """
    parts: list[str] = []

    def _join(items: list | None) -> str | None:
        if not items:
            return None
        return ", ".join(
            item.get("value", str(item)) if isinstance(item, dict) else str(item)
            for item in items
        )

    if joined := _join(dna.values):
        parts.append(f"Values: {joined}")
    if joined := _join(dna.exclusions):
        parts.append(f"Exclusions: {joined}")
    if joined := _join(dna.tilts):
        parts.append(f"Tilts: {joined}")
    if joined := _join(dna.life_events):
        parts.append(f"Life events: {joined}")
    if joined := _join(dna.promises):
        parts.append(f"Promises: {joined}")
    if dna.business_context:
        parts.append(f"Business: {dna.business_context}")
    if dna.family_context:
        parts.append(f"Family: {dna.family_context}")
    if dna.temperament:
        parts.append(f"Temperament: {dna.temperament}")

    return ". ".join(parts) if parts else "No DNA data."
