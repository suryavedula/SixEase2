"""Semantic similarity search over the pgvector embeddings table (TASK-015, EPIC-03).

Embeds an arbitrary query string and returns the nearest neighbours by cosine
distance. Used by DNA extraction (TASK-016/017) and news-theme matching (TASK-028+).
"""

from fastapi import APIRouter, Depends
from pgvector.sqlalchemy import Vector
from pydantic import BaseModel
from sqlalchemy import cast, literal, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.loaders.embeddings import embed_texts
from app.logging import get_logger
from app.models.embedding import Embedding

router = APIRouter(prefix="/similarity", tags=["similarity"])
log = get_logger(__name__)
settings = get_settings()


class SimilarityRequest(BaseModel):
    query: str
    owner_type: str | None = None  # "interaction" | "client_dna" | None = all
    top_k: int = 10


class SimilarityHit(BaseModel):
    owner_type: str
    owner_id: str   # UUID serialised to string for JSON transport
    distance: float  # cosine distance: 0 = identical, 1 = orthogonal


class SimilarityResponse(BaseModel):
    hits: list[SimilarityHit]


@router.post("/search", response_model=SimilarityResponse)
async def similarity_search(
    body: SimilarityRequest,
    session: AsyncSession = Depends(get_session),
) -> SimilarityResponse:
    """Return the top-K most similar embeddings to the query string.

    Uses the HNSW cosine index (ix_embeddings_vector_hnsw) for sub-linear ANN
    retrieval. The query is embedded via the same Ollama model used at seed time.
    """
    vectors = await embed_texts([body.query])
    qv = vectors[0]

    # cast(literal(str(qv)), Vector(...)) passes the Python list as a pgvector
    # literal through SQLAlchemy's type system so the <=> operator receives a
    # properly-typed comparand without raw SQL.
    qv_col = cast(literal(str(qv)), Vector(settings.embed_dim))

    stmt = (
        select(
            Embedding.owner_type,
            Embedding.owner_id,
            Embedding.vector.cosine_distance(qv_col).label("distance"),
        )
        .order_by(Embedding.vector.cosine_distance(qv_col))
        .limit(body.top_k)
    )
    if body.owner_type:
        stmt = stmt.where(Embedding.owner_type == body.owner_type)

    result = await session.execute(stmt)
    rows = result.fetchall()

    hits = [
        SimilarityHit(
            owner_type=row.owner_type,
            owner_id=str(row.owner_id),
            distance=float(row.distance),
        )
        for row in rows
    ]
    log.info(
        "similarity.search",
        query_len=len(body.query),
        owner_type=body.owner_type,
        top_k=body.top_k,
        hits=len(hits),
    )
    return SimilarityResponse(hits=hits)
