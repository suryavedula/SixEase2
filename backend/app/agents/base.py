"""Shared agent protocol for TASK-054 / EPIC-13.

AgentRequest and AgentResult are the uniform contract that every domain agent
exposes. TASK-053's LangGraph nodes call invoke(request, session) on each agent
and receive an AgentResult — no agent-specific knowledge required at the router layer.
"""

import uuid
from typing import Any

from pydantic import BaseModel


class AgentRequest(BaseModel):
    client_id: uuid.UUID
    params: dict[str, Any] = {}  # agent-specific extras (e.g. draft_id, preset, alert_id)


class AgentResult(BaseModel):
    agent: str                   # "crm" | "portfolio" | "news" | "message"
    client_id: uuid.UUID
    status: str                  # "ok" | "error"
    payload: dict[str, Any]      # engine-specific output; empty dict on error
    error: str | None = None
