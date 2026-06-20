"""Channel suggestion logic (TASK-039 / MSG8).

Pure function — no DB access, no I/O. Emotional alert classes prefer a call
over email per MSG8; financial/compliance classes default to email.
'in-person' is reserved for roadmap once the RM calendar integration ships.
"""

_CALL_PREFERRED: frozenset[str] = frozenset({
    "good_news",
    "quiet_client",
    "overdue_promise",
    "panic",
})


def suggest_channel(alert_class: str | None) -> str:
    """Return 'call' or 'email' based on the alert class (MSG8).

    Emotional moments (good news, quiet client, overdue promise, panic)
    prefer a call; financial / compliance alerts default to email.
    """
    if alert_class in _CALL_PREFERRED:
        return "call"
    return "email"
