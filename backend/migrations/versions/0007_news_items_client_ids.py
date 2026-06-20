"""Add client_ids JSONB column to news_items (TASK-028, EPIC-06)

Revision ID: 0007
Revises: 0006
Create Date: 2026-06-20

One article can match multiple clients (fan-out). client_ids stores the UUID
strings of every client it matched so GET /clients/{id}/news can use a single
indexed JSONB containment query instead of joining through positions.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0007"
down_revision: Union[str, None] = "0006"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("news_items", sa.Column("client_ids", postgresql.JSONB(), nullable=True))
    op.create_index(
        "ix_news_client_ids",
        "news_items",
        ["client_ids"],
        postgresql_using="gin",
    )


def downgrade() -> None:
    op.drop_index("ix_news_client_ids", table_name="news_items")
    op.drop_column("news_items", "client_ids")
