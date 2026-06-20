"""Autonomy-boundary classifier (TASK-050, §19.2 TK3, G1).

Single source of truth for which task kinds may auto-run and which must stay
Manual. Callers (task-creation endpoints, agents) use classify_execution_mode
to set execution_mode on a new Task row, and assert_auto_eligible as a guard
before scheduling autonomous execution.
"""

from app.logging import get_logger
from app.models.enums import ExecutionMode, TaskKind

log = get_logger(__name__)

_AUTO_ELIGIBLE: frozenset[TaskKind] = frozenset(
    {
        TaskKind.RESEARCH,
        TaskKind.NEWS_GATHER,
        TaskKind.SWAP_CANDIDATES,
        TaskKind.DRAFT_PREP,
        TaskKind.ANALYSIS,
    }
)


def classify_execution_mode(task_kind: TaskKind) -> ExecutionMode:
    """Return the execution mode mandated by TK3 for this task kind."""
    return ExecutionMode.AUTO if task_kind in _AUTO_ELIGIBLE else ExecutionMode.MANUAL


def assert_auto_eligible(task_kind: TaskKind, context: dict | None = None) -> None:
    """Raise ValueError and log a structured violation if task_kind cannot auto-run (TK3)."""
    if task_kind not in _AUTO_ELIGIBLE:
        log.warning(
            "autonomy.boundary_violation",
            task_kind=task_kind.value,
            **(context or {}),
        )
        raise ValueError(
            f"Task kind '{task_kind.value}' is outward/irreversible and cannot auto-run (TK3). "
            "Set execution_mode=Manual or obtain RM approval."
        )
