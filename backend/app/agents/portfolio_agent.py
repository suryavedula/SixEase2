"""Portfolio Agent — delegates to the Personalization Engine (TASK-054 / EPIC-13).

ST5 mapping: Portfolio Agent → Personalization Engine (loaders/swap.py:compute_swaps).

Finds DNA-aligned, mandate-neutral swap candidates for conflict holdings.
Requires DNA and fit scoring to have run first (seed/dna → seed/fit).
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentRequest, AgentResult
from app.loaders.swap import compute_swaps
from app.logging import get_logger

log = get_logger(__name__)


async def invoke(request: AgentRequest, session: AsyncSession) -> AgentResult:
    """Compute swap proposals for the given client and return proposal counts."""
    client_id = request.client_id
    log.info("agent.invoke.start", agent="portfolio", client_id=str(client_id))

    try:
        result = await compute_swaps(session, client_id=client_id)

        log.info(
            "agent.invoke.done",
            agent="portfolio",
            client_id=str(client_id),
            **result,
        )
        return AgentResult(
            agent="portfolio",
            client_id=client_id,
            status="ok",
            payload=result,
        )

    except Exception as exc:  # noqa: BLE001
        log.error(
            "agent.invoke.error", agent="portfolio", client_id=str(client_id), error=str(exc)
        )
        return AgentResult(
            agent="portfolio",
            client_id=client_id,
            status="error",
            payload={},
            error=str(exc),
        )
