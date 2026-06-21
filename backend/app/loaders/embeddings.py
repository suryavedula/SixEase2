"""Embedding generation and pgvector upsert (TASK-015, EPIC-03).

Calls the Ollama embedding endpoint (OpenAI-compatible /v1/embeddings) via the
existing AsyncOpenAI singleton and writes results into the `embeddings` table.
Idempotent: deletes the existing row for each owner before inserting the new one.

Owner types:
  "interaction" — CRM note (Interaction.note)
  "client_dna"  — flattened ClientDNA attributes
"""

import uuid

from openai import AsyncOpenAI
from pgvector.sqlalchemy import Vector
from sqlalchemy import cast, delete, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.logging import get_logger
from app.models.derived import ClientDNA
from app.models.embedding import Embedding
from app.models.source import Interaction

log = get_logger(__name__)
settings = get_settings()

_BATCH_SIZE = 32  # safe upper bound for Ollama single-request embedding

# Embeddings ALWAYS run on Ollama (`ollama_embed_model`), independent of
# `llm_provider`. The active LLM client (app.llm.get_client) follows LLM_PROVIDER —
# which for a Phoeniqs deployment has no `nomic-embed-text`, so routing embeddings
# through it 400s. This dedicated client pins embeddings to the Ollama endpoint.
_embed_client: AsyncOpenAI | None = None
# Circuit breaker: flips True after the first embedding failure so the relevance
# gate degrades to a no-op (logged once) instead of erroring per article. Reset on
# process restart.
_embeddings_degraded = False


def _get_embed_client() -> AsyncOpenAI:
    global _embed_client
    if _embed_client is None:
        # Ollama ignores the key; the openai SDK rejects an empty string.
        _embed_client = AsyncOpenAI(base_url=settings.ollama_base_url, api_key="nokey")
    return _embed_client


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts via the Ollama /v1/embeddings endpoint.

    Uses a dedicated Ollama-pinned client (NOT the active LLM provider), so
    embeddings work regardless of LLM_PROVIDER. Raises on transport/model error —
    callers that must not block (the relevance gate) catch it; seed jobs let it
    surface so the misconfiguration is fixed at source.
    """
    client = _get_embed_client()
    response = await client.embeddings.create(
        model=settings.ollama_embed_model,
        input=texts,
    )
    return [item.embedding for item in response.data]


async def relevance_distances(session: AsyncSession, text: str) -> dict[str, float]:
    """Cosine distance from an article's embedding to each client's DNA profile vector.

    This is the local, zero-hosted-cost answer to "does this news affect the client
    profile?": embed the article once (Ollama, free) and compare against the already-
    stored `client_dna` vectors via the pgvector HNSW cosine index. Returns
    {client_id_str: distance} with **lower = more on-profile** (0 = identical,
    1 = orthogonal). Clients without a DNA embedding are simply absent — the caller
    treats an absent client as "unknown" and does not gate on it.

    NEVER raises and NEVER blocks the pipeline: the relevance gate is an additive
    precision filter, so if Ollama is unreachable / the gate is disabled, it returns
    {} (no gating) and logs the degradation once, rather than halting news fan-out.
    """
    global _embeddings_degraded
    if _embeddings_degraded or not settings.news_relevance_enabled or not text.strip():
        return {}

    try:
        qv = (await embed_texts([text]))[0]
    except Exception as exc:
        _embeddings_degraded = True  # stop retrying every article; gate becomes no-op
        log.warning(
            "embeddings.relevance_degraded",
            reason=str(exc),
            note="relevance gate disabled until restart; news fan-out continues ungated",
        )
        return {}
    # cast(literal(str(qv)), Vector(...)) hands the Python list to pgvector as a
    # properly-typed comparand for <=> without raw SQL (mirrors routers/similarity).
    qv_col = cast(literal(str(qv)), Vector(settings.embed_dim))
    stmt = (
        select(
            ClientDNA.client_id,
            Embedding.vector.cosine_distance(qv_col).label("distance"),
        )
        .join(Embedding, Embedding.owner_id == ClientDNA.id)
        .where(Embedding.owner_type == "client_dna")
    )
    rows = (await session.execute(stmt)).all()
    return {str(client_id): float(distance) for client_id, distance in rows}


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
