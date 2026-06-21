"""Add rm_follows table (Change Radar "My Topics" tab)

Revision ID: 0013
Revises: 0012
Create Date: 2026-06-21

RM-curated follow list backing the Change Radar "My Topics" tab. Single-RM app:
one global list, no user scoping. Non-destructive: adds one new table, no changes
to existing schema.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: Union[str, None] = "0012"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "rm_follows",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("keyword", sa.Text(), nullable=False),
        sa.Column("entity_key", sa.Text(), nullable=True),
        sa.Column("entity_type", sa.Text(), nullable=True),
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
    op.create_index("ix_rm_follows_keyword", "rm_follows", ["keyword"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_rm_follows_keyword", table_name="rm_follows")
    op.drop_table("rm_follows")
