"""LangGraph StateGraph for the domain-agent orchestrator (TASK-053, EPIC-13).

Graph topology:
  START → route_intent → [conditional] → crm_agent | portfolio_agent | news_agent | message_agent → END

Every domain agent has exactly one outgoing edge to END — no loop edges back to route_intent.
This is the structural guarantee that trust-critical flows (portfolio, message) are deterministic.

Invoke:
    from app.agents import graph, AgentState
    final_state = await graph.ainvoke({
        "task_id":   str(task.id),
        "task_kind": TaskKind.RESEARCH.value,
        "client_id": str(task.client_id),
        "input":     task.title or "",
        "result":    {},
        "trace":     [],
        "error":     None,
    })
"""

from langgraph.graph import END, StateGraph

from app.agents.nodes import (
    crm_agent,
    message_agent,
    news_agent,
    portfolio_agent,
    route_intent,
)
from app.agents.state import AgentState

_ROUTING_MAP: dict[str, str] = {
    "research":        "crm_agent",
    "analysis":        "crm_agent",
    "swap_candidates": "portfolio_agent",
    "news_gather":     "news_agent",
    "draft_prep":      "message_agent",
}


def _routing_fn(state: AgentState) -> str:
    if state.get("error"):
        return END
    return _ROUTING_MAP.get(state["task_kind"], END)


workflow = StateGraph(AgentState)

workflow.add_node("route_intent",    route_intent)
workflow.add_node("crm_agent",       crm_agent)
workflow.add_node("portfolio_agent", portfolio_agent)
workflow.add_node("news_agent",      news_agent)
workflow.add_node("message_agent",   message_agent)

workflow.set_entry_point("route_intent")

workflow.add_conditional_edges(
    "route_intent",
    _routing_fn,
    {
        "crm_agent":       "crm_agent",
        "portfolio_agent": "portfolio_agent",
        "news_agent":      "news_agent",
        "message_agent":   "message_agent",
        END:               END,
    },
)

# Every domain agent terminates — no loops back
workflow.add_edge("crm_agent",       END)
workflow.add_edge("portfolio_agent", END)
workflow.add_edge("news_agent",      END)
workflow.add_edge("message_agent",   END)

graph = workflow.compile()
