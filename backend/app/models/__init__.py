"""ORM models package (TASK-004, EPIC-01).

Declares the single declarative `Base` and imports every model module so that
`Base.metadata` is fully populated whenever this package is imported — which is
what `migrations/env.py` (Alembic autogenerate) and `app.db` rely on.

`Base` is defined *before* the model imports below so submodules can safely do
`from app.models import Base` without a circular-import failure.
"""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared declarative base — one MetaData for the whole schema."""


# Import models for their side effect (registering on Base.metadata). Order is
# source → derived → citation → embedding so FK targets exist first. noqa: E402
# because these must follow the Base definition above.
from app.models.source import (  # noqa: E402
    CIORecommendation,
    Client,
    Interaction,
    MandateStrategy,
    Position,
)
from app.models.derived import (  # noqa: E402
    Alert,
    ClientDNA,
    ClientWatchlist,
    EnrichedHolding,
    MessageDraft,
    Moment,
    NewsItem,
    SwapProposal,
    Task,
)
from app.models.citation import Citation  # noqa: E402
from app.models.embedding import Embedding  # noqa: E402

__all__ = [
    "Base",
    # source
    "Client",
    "Interaction",
    "Position",
    "MandateStrategy",
    "CIORecommendation",
    # derived
    "ClientDNA",
    "ClientWatchlist",
    "EnrichedHolding",
    "NewsItem",
    "MessageDraft",
    "SwapProposal",
    "Moment",
    "Alert",
    "Task",
    # traceability + embeddings
    "Citation",
    "Embedding",
]
