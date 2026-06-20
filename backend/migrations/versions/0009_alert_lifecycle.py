"""Add snoozed_until and dismissed_reason to alerts (TASK-035, EPIC-08)

Revision ID: 0009
Revises: 0008
Create Date: 2026-06-20

Supports AL7 alert lifecycle transitions (act / dismiss / snooze / convert-to-task).

snoozed_until — timestamp stored when RM snoozes an alert; the poller or UI
  uses this to re-surface the alert after the requested delay.

dismissed_reason — free-text calibration signal (UC-26); feeds GROUP BY
  alert_class queries so the system learns which alert types the RM considers
  noise over time. Hits the existing ix_alerts_client_status_severity index.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: Union[str, None] = "0008"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("alerts", sa.Column("snoozed_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("alerts", sa.Column("dismissed_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("alerts", "dismissed_reason")
    op.drop_column("alerts", "snoozed_until")
