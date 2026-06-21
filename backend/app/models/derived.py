"""Derived entities (TASK-004, EPIC-01) — §18.1 "Derived (built by our system)".

These tables are produced by our pipeline, not loaded from the workbooks. This
task only owns their *shape* (the schema contract); the population logic lives
in the owning tasks (016/017 DNA, 020/021 fit/swap, 028+ news, 032 alerts, 037+
messages, 049 tasks). Soft / iterating fields are JSONB so those tasks can evolve
their internal structure without a migration; hard columns + FKs are reserved for
the join / filter / traceability (G2) paths.
"""

import uuid
from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    Enum as SAEnum,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    Text,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models import Base
from app.models.enums import (
    ActionType,
    AlertStatus,
    DraftStatus,
    ExecutionMode,
    Mandate,
    Severity,
    TaskStatus,
)
from app.models.mixins import TimestampMixin, UUIDMixin


class ClientDNA(UUIDMixin, TimestampMixin, Base):
    """The extracted "who they are" (§18.1 ClientDNA). Embedding owner for similarity."""

    __tablename__ = "client_dna"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    mandate: Mapped[Mandate | None] = mapped_column()
    # JSONB soft lists, each item carrying its own {value/tag, source note ref, confidence}.
    values: Mapped[list | None] = mapped_column(JSONB)
    exclusions: Mapped[list | None] = mapped_column(JSONB)  # hard red lines (UC-15)
    tilts: Mapped[list | None] = mapped_column(JSONB)
    life_events: Mapped[list | None] = mapped_column(JSONB)
    promises: Mapped[list | None] = mapped_column(JSONB)  # UC-8
    style_profile: Mapped[dict | None] = mapped_column(JSONB)  # MSG1 tone/frame scores
    business_context: Mapped[str | None] = mapped_column(Text)
    family_context: Mapped[str | None] = mapped_column(Text)
    temperament: Mapped[str | None] = mapped_column(Text)
    version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )


class EnrichedHolding(UUIDMixin, TimestampMixin, Base):
    """Position + live/derived overlay cache (§18.1 EnrichedHolding).

    Tags live here as JSONB until the normalised instrument-tag table (TASK-010)
    exists; fit/conflicts are filled by TASK-020/021.
    """

    __tablename__ = "enriched_holdings"

    position_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("positions.id", ondelete="CASCADE"), nullable=False
    )
    tags: Mapped[dict | None] = mapped_column(JSONB)  # {region/sector/value: [...]}
    live_price: Mapped[float | None] = mapped_column(Numeric(15, 8))
    live_price_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    fit_score: Mapped[float | None] = mapped_column(Float)
    conflicts: Mapped[list | None] = mapped_column(JSONB)

    __table_args__ = (Index("ix_enriched_position", "position_id", unique=True),)


class NewsItem(UUIDMixin, TimestampMixin, Base):
    """A matched news article (§13 / §18.1 NewsItem)."""

    __tablename__ = "news_items"

    headline: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)
    url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sentiment: Mapped[float | None] = mapped_column(Float)
    matched_holdings: Mapped[list | None] = mapped_column(JSONB)  # own-axis (P)
    matched_themes: Mapped[list | None] = mapped_column(JSONB)  # care-axis (DNA)
    impact: Mapped[str | None] = mapped_column(Text)  # threat / opportunity / moment
    event_cluster_id: Mapped[str | None] = mapped_column(Text)  # dedup key (§14.2 AL5)
    # Added by migration 0006 (TASK-031): distinguishes seeded demo articles from live ones.
    is_seeded: Mapped[bool] = mapped_column(Boolean, server_default=text("false"), nullable=False)
    # Added by migration 0007 (TASK-028): UUID strings of clients this article matched.
    client_ids: Mapped[list | None] = mapped_column(JSONB)

    __table_args__ = (
        Index("ix_news_event_cluster", "event_cluster_id"),
        Index("ix_news_client_ids", "client_ids", postgresql_using="gin"),
    )


class MessageDraft(UUIDMixin, TimestampMixin, Base):
    """A tailored advisory draft with locked facts + provenance (§16 / §18.1 MessageDraft)."""

    __tablename__ = "message_drafts"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    fact_sheet: Mapped[dict | None] = mapped_column(JSONB)  # deterministic locked facts (MSG2)
    draft_text: Mapped[str | None] = mapped_column(Text)
    style: Mapped[str | None] = mapped_column(Text)  # data-driven / values-led … (MSG1)
    channel: Mapped[str | None] = mapped_column(Text)
    facts_used: Mapped[list | None] = mapped_column(JSONB)  # MSG4 validation
    provenance: Mapped[list | None] = mapped_column(JSONB)  # claim → source (MSG4, G2)
    status: Mapped[DraftStatus] = mapped_column(
        SAEnum(DraftStatus, name="draft_status", create_type=False),
        default=DraftStatus.DRAFT,
        nullable=False,
    )


class SwapProposal(UUIDMixin, TimestampMixin, Base):
    """A DNA-driven, mandate-neutral instrument swap (§11 / §18.1 SwapProposal)."""

    __tablename__ = "swap_proposals"

    holding_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("positions.id", ondelete="CASCADE"), nullable=False
    )
    candidate_isin: Mapped[str | None] = mapped_column(Text)
    candidate_valor: Mapped[str | None] = mapped_column(Text)
    dna_reason: Mapped[str | None] = mapped_column(Text)
    cio_view: Mapped[str | None] = mapped_column(Text)
    mandate_neutral: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    fit_gain: Mapped[float | None] = mapped_column(Float)
    sources: Mapped[list | None] = mapped_column(JSONB)

    __table_args__ = (Index("ix_swap_holding", "holding_id"),)


class Moment(UUIDMixin, TimestampMixin, Base):
    """A non-financial "moment that matters" reach-out (UC-6 / §18.1 Moment)."""

    __tablename__ = "moments"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    event: Mapped[str | None] = mapped_column(Text)
    why: Mapped[str | None] = mapped_column(Text)
    channel: Mapped[str | None] = mapped_column(Text)
    draft_ref: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("message_drafts.id", ondelete="SET NULL")
    )
    sources: Mapped[list | None] = mapped_column(JSONB)


class Alert(UUIDMixin, TimestampMixin, Base):
    """The convergence-point alert (§15 / §18.1 Alert). Anatomy per AL3."""

    __tablename__ = "alerts"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE"), nullable=False
    )
    alert_class: Mapped[str | None] = mapped_column(Text)
    action_type: Mapped[ActionType] = mapped_column(
        SAEnum(ActionType, name="action_type", create_type=False), nullable=False
    )  # AL2
    severity: Mapped[Severity] = mapped_column(
        SAEnum(Severity, name="severity", create_type=False), nullable=False
    )  # AL4
    due: Mapped[date | None] = mapped_column(Date)
    trigger: Mapped[str | None] = mapped_column(Text)
    why: Mapped[str | None] = mapped_column(Text)  # "why this matters to you" (G3)
    suggested_action: Mapped[str | None] = mapped_column(Text)
    draft_ref: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("message_drafts.id", ondelete="SET NULL")
    )
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[AlertStatus] = mapped_column(
        SAEnum(AlertStatus, name="alert_status", create_type=False),
        default=AlertStatus.OPEN,
        nullable=False,
    )
    evidence: Mapped[list | None] = mapped_column(JSONB)  # citeable triggers (G2)
    rank_score: Mapped[float | None] = mapped_column(Float)  # AL6 prioritisation (TASK-034)
    snoozed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # AL7 snooze
    dismissed_reason: Mapped[str | None] = mapped_column(Text)  # UC-26 calibration signal

    __table_args__ = (Index("ix_alerts_client_status_severity", "client_id", "status", "severity"),)


class Task(UUIDMixin, TimestampMixin, Base):
    """A generated task with selective autonomous execution (§19.2 / §18.1 Task)."""

    __tablename__ = "tasks"

    client_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("clients.id", ondelete="CASCADE")
    )
    alert_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("alerts.id", ondelete="SET NULL")
    )
    title: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str | None] = mapped_column(Text)  # alert / note / promise (TK1)
    execution_mode: Mapped[ExecutionMode] = mapped_column(
        SAEnum(ExecutionMode, name="execution_mode", create_type=False), nullable=False
    )  # TK2
    status: Mapped[TaskStatus] = mapped_column(
        SAEnum(TaskStatus, name="task_status", create_type=False),
        default=TaskStatus.CREATED,
        nullable=False,
    )
    result: Mapped[dict | None] = mapped_column(JSONB)  # cited brief / draft (TK4/TK5, G2)

    __table_args__ = (Index("ix_tasks_client_status", "client_id", "status"),)


class ClientWatchlist(UUIDMixin, TimestampMixin, Base):
    """Per-client watchlist: held entities ∪ DNA themes (§13 / TASK-027).

    Consumed by TASK-028 (news matching) and TASK-029 (global feed poller §14.2 F1).
    """

    __tablename__ = "client_watchlists"

    client_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("clients.id", ondelete="CASCADE"),
        unique=True,
        nullable=False,
    )
    entities: Mapped[list | None] = mapped_column(JSONB)   # [{issuer, isin, valor, ticker}]
    themes: Mapped[list | None] = mapped_column(JSONB)     # [tag_string, ...]
    keywords: Mapped[list | None] = mapped_column(JSONB)   # flat deduped search-term list

    __table_args__ = (Index("ix_watchlist_client", "client_id", unique=True),)


class ChangeEvent(UUIDMixin, TimestampMixin, Base):
    """A book-wide change, event-centric (TASK-059, EPIC-08).

    The event-centric *inversion* of per-client Alert / NewsItem signals: every
    change reduces to one triggering entity (instrument / sector / client / macro),
    fans out to all impacted clients by database-wide exposure, and is scored by
    aggregate impact = Σ_clients(exposure_chf × magnitude × dna_relevance) × recency.

    Materialised (delete-and-reload) by loaders/change_radar.py from POST
    /admin/seed/radar; read top-N by GET /radar. Idempotent: a re-run rebuilds the
    whole table from current Alert / NewsItem state.
    """

    __tablename__ = "change_events"

    action: Mapped[str | None] = mapped_column(Text)  # "Drift breach", "CIO SELL flip", "News threat"…
    entity_key: Mapped[str | None] = mapped_column(Text)  # canonical dedup key: isin: / sac: / news: / client:
    entity_type: Mapped[str | None] = mapped_column(Text)  # instrument | sector | client | macro
    entity_label: Mapped[str | None] = mapped_column(Text)  # human label (issuer, sector, headline)
    source: Mapped[str | None] = mapped_column(Text)  # news | cio | drift | dna | email
    event_ts: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))  # recency input
    magnitude: Mapped[float | None] = mapped_column(Float)  # normalised event magnitude
    impact_score: Mapped[float | None] = mapped_column(Float)  # aggregate Σ(exposure × magnitude × dna) × recency
    client_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("0"))
    total_exposure_chf: Mapped[float | None] = mapped_column(Numeric(15, 2))
    impacted_clients: Mapped[list | None] = mapped_column(JSONB)  # per-client breakdown (G2)
    suggested_batch_action: Mapped[str | None] = mapped_column(Text)  # batch op when one entity hits many
    sources: Mapped[list | None] = mapped_column(JSONB)  # citeable origins (G2)
    # No-fallbacks (TASK-006 / project rule): set when the entity resolved to zero
    # impacted clients — surfaced explicitly, never silently dropped.
    unresolved_reason: Mapped[str | None] = mapped_column(Text)

    __table_args__ = (
        Index("ix_change_events_impact", "impact_score"),
        Index("ix_change_events_entity", "entity_key"),
        Index("ix_change_events_type", "entity_type"),
    )


class RadarDelivery(UUIDMixin, TimestampMixin, Base):
    """Dispatch ledger: what the proactive radar has already pushed to the RM.

    change_events is delete-and-reloaded every refresh, so delivery state cannot
    live there — it keys off the stable `entity_key` here instead. The dispatch
    loop (radar_dispatch.py) checks this table to avoid re-notifying the same change
    (and only re-notifies when impact rises materially above `impact_at_delivery`).
    The daily digest is recorded as one row with channel="digest" and a date-stamped
    entity_key (`digest:YYYY-MM-DD`). RM-only delivery — nothing here reaches a
    client (autonomy boundary G1).
    """

    __tablename__ = "radar_deliveries"

    entity_key: Mapped[str] = mapped_column(Text, nullable=False)
    channel: Mapped[str] = mapped_column(Text, nullable=False)  # sse | email | digest
    delivered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
    impact_at_delivery: Mapped[float | None] = mapped_column(Float)

    __table_args__ = (Index("ix_radar_deliveries_entity", "entity_key"),)


class RmFollow(UUIDMixin, TimestampMixin, Base):
    """An RM-curated "My Topics" follow (Change Radar tabs).

    The relationship manager pins entities/keywords they personally track; the
    Change Radar "My Topics" tab shows only change events matching one of these.
    Single-RM app — one global list, no user scoping. Curated inline from radar
    events (entity_key + label) or added free-text. `keyword` is the lowercased
    match term; an event matches when its `entity_key` equals this row's
    entity_key, or its label/entity_key contains `keyword`. RM-only — never
    touches a client (autonomy boundary G1).
    """

    __tablename__ = "rm_follows"

    label: Mapped[str] = mapped_column(Text, nullable=False)  # human label shown in the UI
    keyword: Mapped[str] = mapped_column(Text, nullable=False)  # lowercased match term (deduped)
    entity_key: Mapped[str | None] = mapped_column(Text)  # canonical key when pinned from an event
    entity_type: Mapped[str | None] = mapped_column(Text)  # instrument | sector | client | macro

    __table_args__ = (Index("ix_rm_follows_keyword", "keyword", unique=True),)
