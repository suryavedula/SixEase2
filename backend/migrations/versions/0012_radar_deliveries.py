"""Add radar_deliveries table (EPIC-08 — proactive dispatch)

Revision ID: 0012
Revises: 0011
Create Date: 2026-06-20

Dispatch ledger for the proactive Change Radar: records what has already been
pushed to the RM so the dispatch loop never re-notifies the same change. Keys off
the stable change_events.entity_key (change_events itself is delete-and-reloaded
every refresh, so delivery state cannot live there). The daily digest is one row
with channel="digest" and a date-stamped entity_key. RM-only — nothing here
reaches a client (autonomy boundary G1).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0012"
down_revision: Union[str, None] = "0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "radar_deliveries",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("entity_key", sa.Text(), nullable=False),
        sa.Column("channel", sa.Text(), nullable=False),
        sa.Column(
            "delivered_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("impact_at_delivery", sa.Float(), nullable=True),
    )
    op.create_index("ix_radar_deliveries_entity", "radar_deliveries", ["entity_key"])


def downgrade() -> None:
    op.drop_index("ix_radar_deliveries_entity", table_name="radar_deliveries")
    op.drop_table("radar_deliveries")
