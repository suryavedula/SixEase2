"""Global watchlist index endpoint (TASK-027, EPIC-06).

Exposes the global union of all clients' watchlist keywords for the news poller
(TASK-029, §14.2 F1). The per-client watchlist endpoint lives in portfolio.py
under GET /clients/{id}/watchlist.
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.loaders.watchlist import get_global_index
from app.logging import get_logger

router = APIRouter(prefix="/watchlist", tags=["watchlist"])
log = get_logger(__name__)


@router.get("/global")
async def get_global_watchlist(session: AsyncSession = Depends(get_session)) -> dict:
    """Global union watchlist index for the news poller (§14.2 F1 / TASK-029).

    Returns the deduplicated union of all clients' entity identifiers and DNA theme
    keywords. Returns empty keywords list gracefully if no watchlists have been built.
    """
    result = await get_global_index(session)
    log.info(
        "watchlist.global_read",
        client_count=result["client_count"],
        keyword_count=result["keyword_count"],
    )
    return result
