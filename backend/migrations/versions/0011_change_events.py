"""Add change_events table (TASK-059, EPIC-08)

Revision ID: 0011
Revises: 0010
Create Date: 2026-06-20

Materialises the book-wide Change Radar: the event-centric inversion of per-client
Alert / NewsItem signals. Each row is one triggering entity (instrument / sector /
client / macro) with its impacted-client fan-out and aggregate impact score.

Built (delete-and-reload) by POST /admin/seed/radar (loaders/change_radar.py);
read top-N by GET /radar. impact_score is indexed for the ORDER BY ... DESC top-N read.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0011"
down_revision: Union[str, None] = "0010"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "change_events",
        sa.Column(
            "id", postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("action", sa.Text()),
        sa.Column("entity_key", sa.Text()),
        sa.Column("entity_type", sa.Text()),
        sa.Column("entity_label", sa.Text()),
        sa.Column("source", sa.Text()),
        sa.Column("event_ts", sa.DateTime(timezone=True)),
        sa.Column("magnitude", sa.Float()),
        sa.Column("impact_score", sa.Float()),
        sa.Column("client_count", sa.Integer(), server_default=sa.text("0"), nullable=False),
        sa.Column("total_exposure_chf", sa.Numeric(15, 2)),
        sa.Column("impacted_clients", postgresql.JSONB()),
        sa.Column("suggested_batch_action", sa.Text()),
        sa.Column("sources", postgresql.JSONB()),
        sa.Column("unresolved_reason", sa.Text()),
    )
    op.create_index("ix_change_events_impact", "change_events", ["impact_score"])
    op.create_index("ix_change_events_entity", "change_events", ["entity_key"])
    op.create_index("ix_change_events_type", "change_events", ["entity_type"])


def downgrade() -> None:
    op.drop_index("ix_change_events_type", table_name="change_events")
    op.drop_index("ix_change_events_entity", table_name="change_events")
    op.drop_index("ix_change_events_impact", table_name="change_events")
    op.drop_table("change_events")
