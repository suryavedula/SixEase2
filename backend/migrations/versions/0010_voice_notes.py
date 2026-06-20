"""Add audio_key to interactions (TASK-048, EPIC-11)

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-20

audio_key — nullable MinIO object key storing the raw voice recording that
  produced this interaction note. Set only when the note originated from a
  voice dictation (TASK-047 / TASK-048 write-back flow); NULL for all existing
  and manually-entered interaction rows.

Key convention: voice-notes/{client_id}/{interaction_id}.webm
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: Union[str, None] = "0009"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("interactions", sa.Column("audio_key", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("interactions", "audio_key")
