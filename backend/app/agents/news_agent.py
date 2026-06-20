"""News Agent — delegates to the Watchlist Monitor engine (TASK-054 / EPIC-13).

ST5 mapping: News Agent → Watchlist Monitor (loaders/news_match.py:scan_news_for_client).

Fetches live articles from Event Registry and matches them against the client's
watchlist (held entities + DNA theme keywords). Requires seed/watchlist to have run first.
"""

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentRequest, AgentResult
from app.loaders.news_match import scan_news_for_client
from app.logging import get_logger

log = get_logger(__name__)


async def invoke(request: AgentRequest, session: AsyncSession) -> AgentResult:
    """Scan live news for the given client and return match/insert counts."""
    client_id = request.client_id
    log.info("agent.invoke.start", agent="news", client_id=str(client_id))

    try:
        result = await scan_news_for_client(session, client_id=client_id)

        log.info(
            "agent.invoke.done",
            agent="news",
            client_id=str(client_id),
            **result,
        )
        return AgentResult(
            agent="news",
            client_id=client_id,
            status="ok",
            payload=result,
        )

    except Exception as exc:  # noqa: BLE001
        log.error("agent.invoke.error", agent="news", client_id=str(client_id), error=str(exc))
        return AgentResult(
            agent="news",
            client_id=client_id,
            status="error",
            payload={},
            error=str(exc),
        )
