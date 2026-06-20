"""Firehose-filter news poller (TASK-029, EPIC-07).

Single sequential background task that polls the Event Registry recent-activity
feed filtered to the global client watchlist, advances the newestUri cursor for
gapless coverage, and enqueues every returned article to Redis for TASK-028 to
fan-out to individual clients (§14.2 F1/F2).

Usage (from main.py lifespan):
    task = start_poller()    # startup
    await stop_poller(task)  # shutdown
"""

import asyncio
import contextlib

from app.config import get_settings
from app.db import SessionFactory
from app.loaders.watchlist import get_global_index
from app.logging import get_logger
from app.news import get_recent_activity
from app.redis_client import cache_get, cache_set, enqueue

settings = get_settings()
log = get_logger(__name__)

_CURSOR_KEY = "news:cursor"
_CANDIDATE_QUEUE = "news:candidates"


async def run_poller() -> None:
    """Infinite poll loop: load index → poll feed → enqueue → persist cursor → sleep."""
    log.info("poller.started", interval=settings.news_poll_interval)
    while True:
        try:
            async with SessionFactory() as session:
                index = await get_global_index(session)
            keywords: list[str] = index["keywords"]

            if not keywords:
                log.warning("poller.no_keywords", hint="seed watchlists first")
                await asyncio.sleep(settings.news_poll_interval)
                continue

            cached = await cache_get(_CURSOR_KEY)
            cursor: str | None = cached["cursor"] if cached else None

            articles, new_cursor = await get_recent_activity(cursor, keywords=keywords)

            for article in articles:
                await enqueue(_CANDIDATE_QUEUE, article.model_dump())

            if new_cursor:
                await cache_set(_CURSOR_KEY, {"cursor": new_cursor})

            log.info(
                "poller.cycle",
                fetched=len(articles),
                enqueued=len(articles),
                cursor=new_cursor,
            )
        except asyncio.CancelledError:
            raise  # propagate so stop_poller() can await cleanly
        except Exception as exc:
            log.warning("poller.cycle_error", error=str(exc))

        await asyncio.sleep(settings.news_poll_interval)


def start_poller() -> "asyncio.Task[None]":
    """Spawn the poller as a named asyncio background task."""
    return asyncio.create_task(run_poller(), name="news-poller")


async def stop_poller(task: "asyncio.Task[None]") -> None:
    """Cancel the poller and wait for it to finish."""
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    log.info("poller.stopped")
