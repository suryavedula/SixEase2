"""Domain enumerations (TASK-004, EPIC-01).

Native Postgres enums for the closed value sets defined in the requirements.
Stored via SQLAlchemy's `Enum(..., name=...)`; each `name` becomes a PG type.
Values mirror the requirement text (mandates §10, AL2/AL4 alert dimensions,
TK2 execution modes) so loaders and downstream tasks share one vocabulary.
"""

import enum


class Mandate(str, enum.Enum):
    """Investment mandate (§10) — the invariant strategy (G4)."""

    DEFENSIVE = "Defensive"
    BALANCED = "Balanced"
    GROWTH = "Growth"


class CIORating(str, enum.Enum):
    """CIO recommendation rating (§10.2 CIO Recommendation List)."""

    BUY = "BUY"
    HOLD = "HOLD"
    SELL = "SELL"


class ActionType(str, enum.Enum):
    """Implied alert action type (§15 AL2) — not every alert is a trade."""

    TRADE = "Trade"
    REACH_OUT = "ReachOut"
    ACKNOWLEDGE = "Acknowledge"
    WATCH = "Watch"


class Severity(str, enum.Enum):
    """Alert severity tiers (§15 AL4)."""

    CRITICAL = "Critical"
    ATTENTION = "Attention"
    FYI = "FYI"


class AlertStatus(str, enum.Enum):
    """Alert lifecycle (§15 AL7, human-in-the-loop G1)."""

    OPEN = "open"
    ACTED = "acted"
    DISMISSED = "dismissed"
    SNOOZED = "snoozed"
    CONVERTED = "converted"  # → task


class DraftStatus(str, enum.Enum):
    """Message-draft lifecycle (§16)."""

    DRAFT = "draft"
    APPROVED = "approved"
    SENT = "sent"
    DISMISSED = "dismissed"


class ExecutionMode(str, enum.Enum):
    """Task execution mode (§19.2 TK2). Auto is bounded by the autonomy rule (TK3)."""

    AUTO = "Auto"
    MANUAL = "Manual"


class TaskStatus(str, enum.Enum):
    """Task lifecycle (§19.2 TK6)."""

    CREATED = "created"
    RUNNING = "running"
    DONE = "done"
    CLOSED = "closed"


class SourceType(str, enum.Enum):
    """Evidence source kind for traceability (G2) — see Citation."""

    CRM_NOTE = "crm_note"
    NEWS = "news"
    CIO = "cio"


class TaskKind(str, enum.Enum):
    """Closed vocabulary of task kinds (§19.2 TK3).

    Auto-eligible: read-only / analysis / research / draft-prep.
    Manual-forced: outward or irreversible actions (G1).
    """

    # Auto-eligible
    RESEARCH = "research"
    NEWS_GATHER = "news_gather"
    SWAP_CANDIDATES = "swap_candidates"
    DRAFT_PREP = "draft_prep"
    ANALYSIS = "analysis"
    # Manual-forced (outward / irreversible)
    CONTACT_CLIENT = "contact_client"
    PLACE_ORDER = "place_order"
    SEND_MESSAGE = "send_message"
    CRM_WRITEBACK = "crm_writeback"
