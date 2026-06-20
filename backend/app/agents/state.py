"""Shared state type for the LangGraph orchestrator (TASK-053, EPIC-13)."""

from typing import TypedDict


class AgentState(TypedDict):
    task_id: str           # UUID string — for log correlation only, not DB access
    task_kind: str         # TaskKind.value (routing key) or free-form NL (route_intent classifies)
    client_id: str | None  # UUID string or None for non-client tasks
    input: str             # Task.title / NL description; used only when task_kind is free-form
    result: dict           # accumulated output; caller writes this to Task.result JSONB
    trace: list[str]       # TK5 observable action log; each node appends one timestamped entry
    error: str | None      # first exception string; signals graph to short-circuit to END
