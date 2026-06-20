"""Reusable column mixins (TASK-004, EPIC-01).

UUID primary keys (`gen_random_uuid()` — built into Postgres 16, no pgcrypto
needed) and audit timestamps, declared SQLAlchemy-2.0 style so every table gets
the same surrogate-key + audit shape without repetition.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column


class UUIDMixin:
    """Non-guessable UUID surrogate key, generated server-side."""

    id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    """`created_at` / `updated_at`, both maintained by the database."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
