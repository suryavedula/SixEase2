"""Vector embeddings (TASK-004, EPIC-01) — satisfies the pgvector AC.

One polymorphic table serves every embeddable entity (Interaction notes AND
ClientDNA), so a single ANN index covers all similarity search. The column
dimension is driven by `Settings.embed_dim` (default 768, `nomic-embed-text`);
TASK-015 owns the actual embedding generation and must agree on the dimension.
"""

import uuid

from pgvector.sqlalchemy import Vector
from sqlalchemy import Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.config import get_settings
from app.models import Base
from app.models.mixins import TimestampMixin, UUIDMixin

EMBED_DIM = get_settings().embed_dim


class Embedding(UUIDMixin, TimestampMixin, Base):
    """A vector for any owner row, addressed polymorphically by (owner_type, owner_id)."""

    __tablename__ = "embeddings"

    owner_type: Mapped[str] = mapped_column(Text, nullable=False)  # "interaction" | "client_dna"
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    model: Mapped[str | None] = mapped_column(Text)  # embedding model id (provenance)
    vector: Mapped[list[float]] = mapped_column(Vector(EMBED_DIM), nullable=False)

    __table_args__ = (
        Index("ix_embeddings_owner", "owner_type", "owner_id"),
        # ANN index for cosine similarity search (HNSW: good recall, no training step).
        Index(
            "ix_embeddings_vector_hnsw",
            "vector",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"vector": "vector_cosine_ops"},
        ),
    )
