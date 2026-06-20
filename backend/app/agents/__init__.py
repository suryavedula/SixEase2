"""Domain agents package (TASK-053 + TASK-054 / EPIC-13).

TASK-053 adds the LangGraph orchestrator (graph + AgentState).
TASK-054 adds the four domain agents with a uniform invoke() protocol.

Usage — orchestrator:
    from app.agents import graph, AgentState
    final_state = await graph.ainvoke({...})

Usage — individual agents:
    from app.agents import crm_agent
    result = await crm_agent.invoke(request, session)
"""

from app.agents import crm_agent, message_agent, news_agent, portfolio_agent
from app.agents.base import AgentRequest, AgentResult
from app.agents.graph import graph
from app.agents.state import AgentState

__all__ = [
    "AgentRequest",
    "AgentResult",
    "AgentState",
    "crm_agent",
    "graph",
    "message_agent",
    "news_agent",
    "portfolio_agent",
]
