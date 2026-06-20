"""Add is_seeded column to news_items (TASK-031, EPIC-07)

Revision ID: 0006
Revises: 0005
Create Date: 2026-06-20

Non-destructive: adds one boolean column with a false default so existing
rows are automatically treated as live/non-seeded data.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "news_items",
        sa.Column(
            "is_seeded",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("news_items", "is_seeded")
