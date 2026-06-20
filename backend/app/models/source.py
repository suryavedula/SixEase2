"""Source entities (TASK-004, EPIC-01) — §18.1 "Source (from workbooks)".

These tables hold ground-truth data loaded verbatim from the two workbooks by
TASK-008 (portfolio) and TASK-009 (CRM). Columns follow the §10 conventions:
CHF amounts as NUMERIC, Valor/MIC/ISIN/Yahoo as text, and Excel-serial dates
stored as DATE *after* the loaders convert them. `Client` is implied by §18.1
(every derived entity references a client) — the four personas live here.
"""

import uuid
from datetime import date

from sqlalchemy import Boolean, Date, Enum as SAEnum, ForeignKey, Index, Numeric, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models import Base
from app.models.enums import CIORating, Mandate
from app.models.mixins import TimestampMixin, UUIDMixin


class Client(UUIDMixin, TimestampMixin, Base):
    """A wealth-management client (the four personas: Räber, Schneider, Huber, Ammann)."""

    __tablename__ = "clients"

    name: Mapped[str] = mapped_column(Text, nullable=False)
    mandate: Mapped[Mandate] = mapped_column(nullable=False)

    interactions: Mapped[list["Interaction"]] = relationship(back_populates="client")
    positions: Mapped[list["Position"]] = relationship(back_populates="client")


class Interaction(UUIDMixin, TimestampMixin, Base):
    """A CRM contact-log entry (§10.1). The `note` is the embedding owner for DNA search (G2)."""

    __tablename__ = "interactions"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    date: Mapped[date | None] = mapped_column(Date)  # Excel serial → DATE (loader converts)
    medium: Mapped[str | None] = mapped_column(Text)
    rm_name: Mapped[str | None] = mapped_column(Text)
    client_contact: Mapped[str | None] = mapped_column(Text)
    note: Mapped[str | None] = mapped_column(Text)
    audio_key: Mapped[str | None] = mapped_column(Text)  # MinIO key; None for non-voice notes

    client: Mapped["Client"] = relationship(back_populates="interactions")

    __table_args__ = (Index("ix_interactions_client_date", "client_id", "date"),)


class Position(UUIDMixin, TimestampMixin, Base):
    """A portfolio holding (§10.2 "Sample Portfolio *").

    The (sub_asset_class, industry_group) pair is the swap match key (E3): the
    invariant slot a personalised instrument must fill without changing strategy.
    """

    __tablename__ = "positions"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    asset_class: Mapped[str | None] = mapped_column(Text)
    sub_asset_class: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    industry_group: Mapped[str | None] = mapped_column(Text)
    issuer: Mapped[str | None] = mapped_column(Text)
    security: Mapped[str | None] = mapped_column(Text)
    isin: Mapped[str | None] = mapped_column(Text)
    valor: Mapped[str | None] = mapped_column(Text)
    mic: Mapped[str | None] = mapped_column(Text)
    yahoo: Mapped[str | None] = mapped_column(Text)
    target_chf: Mapped[float | None] = mapped_column(Numeric(15, 2))
    current_chf: Mapped[float | None] = mapped_column(Numeric(15, 2))
    quantity: Mapped[float | None] = mapped_column(Numeric(18, 8))  # bonds: face ÷ 100

    client: Mapped["Client"] = relationship(back_populates="positions")

    __table_args__ = (
        Index("ix_positions_valor", "valor"),
        Index("ix_positions_isin", "isin"),
        Index("ix_positions_slot", "sub_asset_class", "industry_group"),
    )


class MandateStrategy(UUIDMixin, TimestampMixin, Base):
    """CIO sub-asset-class target weights per mandate (§10.2 "Portfolio Strategies").

    The invariant (G4): weights are never altered by personalisation.
    """

    __tablename__ = "mandate_strategies"

    mandate: Mapped[Mandate] = mapped_column(nullable=False)
    sub_asset_class: Mapped[str] = mapped_column(Text, nullable=False)
    target_weight: Mapped[float] = mapped_column(Numeric(5, 2), nullable=False)

    __table_args__ = (
        Index("ix_mandate_strategies_mandate_sac", "mandate", "sub_asset_class", unique=True),
    )


class CIORecommendation(UUIDMixin, TimestampMixin, Base):
    """A CIO recommendation-list row (§10.2). BUY rows are the swap universe (E4)."""

    __tablename__ = "cio_recommendations"

    rating: Mapped[CIORating] = mapped_column(
        SAEnum(CIORating, name="cio_rating", create_type=False), nullable=False
    )
    rating_since: Mapped[date | None] = mapped_column(Date)
    as_of: Mapped[date | None] = mapped_column(Date)
    asset_class: Mapped[str | None] = mapped_column(Text)
    sub_asset_class: Mapped[str | None] = mapped_column(Text)
    region: Mapped[str | None] = mapped_column(Text)
    industry_group: Mapped[str | None] = mapped_column(Text)
    issuer: Mapped[str | None] = mapped_column(Text)
    security: Mapped[str | None] = mapped_column(Text)
    isin: Mapped[str | None] = mapped_column(Text)
    valor: Mapped[str | None] = mapped_column(Text)
    mic: Mapped[str | None] = mapped_column(Text)
    yahoo: Mapped[str | None] = mapped_column(Text)
    cio_view: Mapped[str | None] = mapped_column(Text)  # citeable rationale (G2)
    # True for not-currently-held BUY swap candidates (§10.2).
    is_swap_candidate: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tags: Mapped[dict | None] = mapped_column(JSONB)  # {sector, region, value_tags} — set by TASK-010

    __table_args__ = (
        Index("ix_cio_industry_group", "industry_group"),
        Index("ix_cio_rating", "rating"),
    )
