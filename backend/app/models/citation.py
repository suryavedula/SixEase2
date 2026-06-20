"""Traceability evidence links (TASK-004, EPIC-01) — satisfies G2.

A single polymorphic table that records "this derived row is backed by that
source row". It complements the hard FKs already on the derived entities
(`Alert.draft_ref`, `SwapProposal.holding_id`, `Task.alert_id`): those capture
1:1/1:N links that are known at the schema level, while `Citation` captures the
many-to-many "claim ↔ evidence" relationship uniformly and queryably across
Alert / ClientDNA / SwapProposal / MessageDraft / Moment.
"""

import uuid

from sqlalchemy import Enum as SAEnum, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base
from app.models.enums import SourceType
from app.models.mixins import TimestampMixin, UUIDMixin


class Citation(UUIDMixin, TimestampMixin, Base):
    """One evidence link: owner (derived row) → source (crm_note / news / cio)."""

    __tablename__ = "citations"

    # Polymorphic owner — the derived entity making the claim.
    owner_type: Mapped[str] = mapped_column(Text, nullable=False)  # e.g. "alert", "client_dna"
    owner_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)

    # The source backing it. source_id points at interactions / news_items /
    # cio_recommendations.id depending on source_type (not a hard FK by design —
    # the table is polymorphic across three source tables).
    source_type: Mapped[SourceType] = mapped_column(
        SAEnum(SourceType, name="source_type", create_type=False), nullable=False
    )
    source_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), nullable=False)
    note: Mapped[str | None] = mapped_column(Text)  # optional quoted snippet

    __table_args__ = (
        Index("ix_citations_owner", "owner_type", "owner_id"),
        Index("ix_citations_source", "source_type", "source_id"),
    )
