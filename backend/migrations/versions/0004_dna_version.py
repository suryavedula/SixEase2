"""Add version column to client_dna (TASK-018, EPIC-04)

Revision ID: 0004
Revises: 0003
Create Date: 2026-06-20

Non-destructive ADD COLUMN — existing rows get version = 1 via the column
DEFAULT. Re-extractions (POST /admin/seed/dna) auto-increment via the upsert
conflict handler in loaders/dna.py.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0004"
down_revision: Union[str, None] = "0003"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "client_dna",
        sa.Column("version", sa.Integer(), nullable=False, server_default=sa.text("1")),
    )


def downgrade() -> None:
    op.drop_column("client_dna", "version")
