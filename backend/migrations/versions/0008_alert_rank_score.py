"""Add rank_score float to alerts (TASK-034, EPIC-08)

Revision ID: 0008
Revises: 0007
Create Date: 2026-06-20

Persists the AL6 prioritisation score (impact × relevance × urgency × emotional-weight)
so the alert read endpoint can ORDER BY rank_score DESC at the DB layer and the book
view can sort clients by their highest-priority open alert without a Python sort pass.

Populated by POST /admin/seed/rank (loaders/alert_rank.py). Nullable so existing rows
remain valid before the first seed/rank run.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("rank_score", sa.Float(), nullable=True))
    op.create_index("ix_alerts_client_rank", "alerts", ["client_id", "rank_score"])


def downgrade() -> None:
    op.drop_index("ix_alerts_client_rank", table_name="alerts")
    op.drop_column("alerts", "rank_score")
