"""Add tags column to cio_recommendations (TASK-010, EPIC-02)

Revision ID: 0003
Revises: 0002
Create Date: 2026-06-20

Non-destructive ADD COLUMN — existing rows get tags = NULL until the
instrument tag loader (POST /admin/seed/tags) populates them.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003"
down_revision: Union[str, None] = "0002"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "cio_recommendations",
        sa.Column("tags", postgresql.JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cio_recommendations", "tags")
