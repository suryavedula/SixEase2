"""Add client_watchlists table (TASK-027, EPIC-06)

Revision ID: 0005
Revises: 0004
Create Date: 2026-06-20

Per-client watchlist: held entities (issuer/ticker/ISIN) UNION DNA themes.
Consumed by TASK-028 (news matching) and TASK-029 (global feed poller §14.2 F1).
Non-destructive: adds one new table, no changes to existing schema.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "client_watchlists",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "client_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("clients.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("entities", postgresql.JSONB(), nullable=True),
        sa.Column("themes", postgresql.JSONB(), nullable=True),
        sa.Column("keywords", postgresql.JSONB(), nullable=True),
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
    )
    op.create_index(
        "ix_watchlist_client", "client_watchlists", ["client_id"], unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_watchlist_client", table_name="client_watchlists")
    op.drop_table("client_watchlists")
