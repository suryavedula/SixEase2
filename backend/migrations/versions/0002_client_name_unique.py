"""Add unique constraint on clients.name (TASK-008, EPIC-02)

Revision ID: 0002
Revises: 0001
Create Date: 2026-06-20

Enables upsert-by-name for seed clients (portfolio loader) and persona
deduplication (CRM loader TASK-009). Without this constraint the
INSERT ... ON CONFLICT (name) DO NOTHING dialect fails at runtime.
"""
from typing import Sequence, Union

from alembic import op

revision: str = "0002"
down_revision: Union[str, None] = "0001"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_unique_constraint("uq_clients_name", "clients", ["name"])


def downgrade() -> None:
    op.drop_constraint("uq_clients_name", "clients", type_="unique")
