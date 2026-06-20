"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-06-20

Materialises every §18.1 entity (+ Task §19.2, Citation for G2, Embedding for
pgvector). Native PG enums are created first, then tables in FK-dependency
order, then lookup / ANN / GIN indexes. Enum labels are the Python enum member
*names* (SQLAlchemy's default persistence for native enums).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector
from sqlalchemy.dialects import postgresql

from app.config import get_settings

# revision identifiers, used by Alembic.
revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

EMBED_DIM = get_settings().embed_dim

# --- Native enum types (labels = Python enum member names) ------------------
mandate = postgresql.ENUM("DEFENSIVE", "BALANCED", "GROWTH", name="mandate", create_type=False)
cio_rating = postgresql.ENUM("BUY", "HOLD", "SELL", name="cio_rating", create_type=False)
action_type = postgresql.ENUM(
    "TRADE", "REACH_OUT", "ACKNOWLEDGE", "WATCH", name="action_type", create_type=False
)
severity = postgresql.ENUM("CRITICAL", "ATTENTION", "FYI", name="severity", create_type=False)
alert_status = postgresql.ENUM(
    "OPEN", "ACTED", "DISMISSED", "SNOOZED", "CONVERTED", name="alert_status", create_type=False
)
draft_status = postgresql.ENUM(
    "DRAFT", "APPROVED", "SENT", "DISMISSED", name="draft_status", create_type=False
)
execution_mode = postgresql.ENUM("AUTO", "MANUAL", name="execution_mode", create_type=False)
task_status = postgresql.ENUM(
    "CREATED", "RUNNING", "DONE", "CLOSED", name="task_status", create_type=False
)
source_type = postgresql.ENUM("CRM_NOTE", "NEWS", "CIO", name="source_type", create_type=False)

_ALL_ENUMS = (
    mandate,
    cio_rating,
    action_type,
    severity,
    alert_status,
    draft_status,
    execution_mode,
    task_status,
    source_type,
)


def _ts_cols() -> list:
    """created_at / updated_at, maintained by the DB (mirrors TimestampMixin)."""
    return [
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
    ]


def _id_col() -> sa.Column:
    return sa.Column(
        "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
    )


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")
    for e in _ALL_ENUMS:
        e.create(bind, checkfirst=True)

    # --- Source ------------------------------------------------------------
    op.create_table(
        "clients",
        _id_col(),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("mandate", mandate, nullable=False),
        *_ts_cols(),
    )

    op.create_table(
        "interactions",
        _id_col(),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("date", sa.Date()),
        sa.Column("medium", sa.Text()),
        sa.Column("rm_name", sa.Text()),
        sa.Column("client_contact", sa.Text()),
        sa.Column("note", sa.Text()),
        *_ts_cols(),
    )
    op.create_index("ix_interactions_client_date", "interactions", ["client_id", "date"])

    op.create_table(
        "positions",
        _id_col(),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("asset_class", sa.Text()),
        sa.Column("sub_asset_class", sa.Text()),
        sa.Column("region", sa.Text()),
        sa.Column("industry_group", sa.Text()),
        sa.Column("issuer", sa.Text()),
        sa.Column("security", sa.Text()),
        sa.Column("isin", sa.Text()),
        sa.Column("valor", sa.Text()),
        sa.Column("mic", sa.Text()),
        sa.Column("yahoo", sa.Text()),
        sa.Column("target_chf", sa.Numeric(15, 2)),
        sa.Column("current_chf", sa.Numeric(15, 2)),
        sa.Column("quantity", sa.Numeric(18, 8)),
        *_ts_cols(),
    )
    op.create_index("ix_positions_valor", "positions", ["valor"])
    op.create_index("ix_positions_isin", "positions", ["isin"])
    op.create_index("ix_positions_slot", "positions", ["sub_asset_class", "industry_group"])

    op.create_table(
        "mandate_strategies",
        _id_col(),
        sa.Column("mandate", mandate, nullable=False),
        sa.Column("sub_asset_class", sa.Text(), nullable=False),
        sa.Column("target_weight", sa.Numeric(5, 2), nullable=False),
        *_ts_cols(),
    )
    op.create_index("ix_mandate_strategies_mandate_sac", "mandate_strategies", ["mandate", "sub_asset_class"], unique=True)

    op.create_table(
        "cio_recommendations",
        _id_col(),
        sa.Column("rating", cio_rating, nullable=False),
        sa.Column("rating_since", sa.Date()),
        sa.Column("as_of", sa.Date()),
        sa.Column("asset_class", sa.Text()),
        sa.Column("sub_asset_class", sa.Text()),
        sa.Column("region", sa.Text()),
        sa.Column("industry_group", sa.Text()),
        sa.Column("issuer", sa.Text()),
        sa.Column("security", sa.Text()),
        sa.Column("isin", sa.Text()),
        sa.Column("valor", sa.Text()),
        sa.Column("mic", sa.Text()),
        sa.Column("yahoo", sa.Text()),
        sa.Column("cio_view", sa.Text()),
        sa.Column("is_swap_candidate", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        *_ts_cols(),
    )
    op.create_index("ix_cio_industry_group", "cio_recommendations", ["industry_group"])
    op.create_index("ix_cio_rating", "cio_recommendations", ["rating"])

    # --- Derived -----------------------------------------------------------
    op.create_table(
        "message_drafts",
        _id_col(),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("fact_sheet", postgresql.JSONB()),
        sa.Column("draft_text", sa.Text()),
        sa.Column("style", sa.Text()),
        sa.Column("channel", sa.Text()),
        sa.Column("facts_used", postgresql.JSONB()),
        sa.Column("provenance", postgresql.JSONB()),
        sa.Column("status", draft_status, server_default=sa.text("'DRAFT'"), nullable=False),
        *_ts_cols(),
    )

    op.create_table(
        "client_dna",
        _id_col(),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("mandate", mandate),
        sa.Column("values", postgresql.JSONB()),
        sa.Column("exclusions", postgresql.JSONB()),
        sa.Column("tilts", postgresql.JSONB()),
        sa.Column("life_events", postgresql.JSONB()),
        sa.Column("promises", postgresql.JSONB()),
        sa.Column("style_profile", postgresql.JSONB()),
        sa.Column("business_context", sa.Text()),
        sa.Column("family_context", sa.Text()),
        sa.Column("temperament", sa.Text()),
        *_ts_cols(),
    )

    op.create_table(
        "enriched_holdings",
        _id_col(),
        sa.Column("position_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("positions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("tags", postgresql.JSONB()),
        sa.Column("live_price", sa.Numeric(15, 8)),
        sa.Column("live_price_at", sa.DateTime(timezone=True)),
        sa.Column("fit_score", sa.Float()),
        sa.Column("conflicts", postgresql.JSONB()),
        *_ts_cols(),
    )
    op.create_index("ix_enriched_position", "enriched_holdings", ["position_id"], unique=True)

    op.create_table(
        "news_items",
        _id_col(),
        sa.Column("headline", sa.Text()),
        sa.Column("source", sa.Text()),
        sa.Column("url", sa.Text()),
        sa.Column("published_at", sa.DateTime(timezone=True)),
        sa.Column("sentiment", sa.Float()),
        sa.Column("matched_holdings", postgresql.JSONB()),
        sa.Column("matched_themes", postgresql.JSONB()),
        sa.Column("impact", sa.Text()),
        sa.Column("event_cluster_id", sa.Text()),
        *_ts_cols(),
    )
    op.create_index("ix_news_event_cluster", "news_items", ["event_cluster_id"])
    op.create_index("ix_news_matched_holdings", "news_items", ["matched_holdings"], postgresql_using="gin")
    op.create_index("ix_news_matched_themes", "news_items", ["matched_themes"], postgresql_using="gin")

    op.create_table(
        "swap_proposals",
        _id_col(),
        sa.Column("holding_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("positions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("candidate_isin", sa.Text()),
        sa.Column("candidate_valor", sa.Text()),
        sa.Column("dna_reason", sa.Text()),
        sa.Column("cio_view", sa.Text()),
        sa.Column("mandate_neutral", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("fit_gain", sa.Float()),
        sa.Column("sources", postgresql.JSONB()),
        *_ts_cols(),
    )
    op.create_index("ix_swap_holding", "swap_proposals", ["holding_id"])

    op.create_table(
        "moments",
        _id_col(),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("event", sa.Text()),
        sa.Column("why", sa.Text()),
        sa.Column("channel", sa.Text()),
        sa.Column("draft_ref", postgresql.UUID(as_uuid=True), sa.ForeignKey("message_drafts.id", ondelete="SET NULL")),
        sa.Column("sources", postgresql.JSONB()),
        *_ts_cols(),
    )

    op.create_table(
        "alerts",
        _id_col(),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("alert_class", sa.Text()),
        sa.Column("action_type", action_type, nullable=False),
        sa.Column("severity", severity, nullable=False),
        sa.Column("due", sa.Date()),
        sa.Column("trigger", sa.Text()),
        sa.Column("why", sa.Text()),
        sa.Column("suggested_action", sa.Text()),
        sa.Column("draft_ref", postgresql.UUID(as_uuid=True), sa.ForeignKey("message_drafts.id", ondelete="SET NULL")),
        sa.Column("confidence", sa.Float()),
        sa.Column("status", alert_status, server_default=sa.text("'OPEN'"), nullable=False),
        sa.Column("evidence", postgresql.JSONB()),
        *_ts_cols(),
    )
    op.create_index("ix_alerts_client_status_severity", "alerts", ["client_id", "status", "severity"])

    op.create_table(
        "tasks",
        _id_col(),
        sa.Column("client_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("clients.id", ondelete="CASCADE")),
        sa.Column("alert_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("alerts.id", ondelete="SET NULL")),
        sa.Column("title", sa.Text()),
        sa.Column("source", sa.Text()),
        sa.Column("execution_mode", execution_mode, nullable=False),
        sa.Column("status", task_status, server_default=sa.text("'CREATED'"), nullable=False),
        sa.Column("result", postgresql.JSONB()),
        *_ts_cols(),
    )
    op.create_index("ix_tasks_client_status", "tasks", ["client_id", "status"])

    # --- Traceability (G2) -------------------------------------------------
    op.create_table(
        "citations",
        _id_col(),
        sa.Column("owner_type", sa.Text(), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source_type", source_type, nullable=False),
        sa.Column("source_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("note", sa.Text()),
        *_ts_cols(),
    )
    op.create_index("ix_citations_owner", "citations", ["owner_type", "owner_id"])
    op.create_index("ix_citations_source", "citations", ["source_type", "source_id"])

    # --- Embeddings (pgvector) --------------------------------------------
    op.create_table(
        "embeddings",
        _id_col(),
        sa.Column("owner_type", sa.Text(), nullable=False),
        sa.Column("owner_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("model", sa.Text()),
        sa.Column("vector", Vector(EMBED_DIM), nullable=False),
        *_ts_cols(),
    )
    op.create_index("ix_embeddings_owner", "embeddings", ["owner_type", "owner_id"])
    op.create_index(
        "ix_embeddings_vector_hnsw",
        "embeddings",
        ["vector"],
        postgresql_using="hnsw",
        postgresql_with={"m": 16, "ef_construction": 64},
        postgresql_ops={"vector": "vector_cosine_ops"},
    )


def downgrade() -> None:
    bind = op.get_bind()
    for table in (
        "embeddings",
        "citations",
        "tasks",
        "alerts",
        "moments",
        "swap_proposals",
        "news_items",
        "enriched_holdings",
        "client_dna",
        "message_drafts",
        "cio_recommendations",
        "mandate_strategies",
        "positions",
        "interactions",
        "clients",
    ):
        op.drop_table(table)
    for e in reversed(_ALL_ENUMS):
        e.drop(bind, checkfirst=True)
