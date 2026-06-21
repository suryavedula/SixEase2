"""Proactive Change Radar refresh (EPIC-08 — the proactive layer).

The poller + fanout already ingest news and match it to clients continuously in
the background. The radar (`change_events`) is a materialised snapshot that would
otherwise only refresh on a manual POST /admin/seed/radar — so freshly-matched
news never surfaces until someone asks. This task re-materialises the snapshot on
an interval, so the radar the RM opens is always current: the agent surfacing
changes *proactively* rather than only reacting to an explicit scan.

Pure aggregation from existing Alert + NewsItem state (no LLM), so it spends zero
hosted-LLM (Phoeniqs) budget. Email signals (TASK-060) are folded in only when MS
Graph is configured; otherwise that step is a no-op.

Usage (from main.py lifespan):
    task = start_radar_refresh()    # startup
    await stop_radar_refresh(task)  # shutdown
"""

import asyncio
import contextlib

from app.config import get_settings
from app.db import SessionFactory
from app.loaders.change_radar import build_change_radar
from app.loaders.email_ingest import ingest_email_signals
from app.logging import get_logger

settings = get_settings()
log = get_logger(__name__)


async def run_radar_refresh() -> None:
    """Infinite loop: rebuild the radar snapshot, then sleep one interval.

    Rebuilds immediately on the first iteration so the radar is current as soon as
    the app is up. `build_change_radar` is a delete-and-reload inside a transaction,
    so concurrent reads see the old or new snapshot, never a partial one.
    """
    log.info("radar_refresh.started", interval=settings.radar_refresh_interval)
    while True:
        try:
            async with SessionFactory() as session:
                extra = (
                    await ingest_email_signals(session)
                    if settings.ms_graph_enabled
                    else []
                )
                counts = await build_change_radar(session, extra_signals=extra)
            log.info("radar_refresh.cycle", **counts)
        except asyncio.CancelledError:
            raise  # propagate so stop_radar_refresh() can await cleanly
        except Exception as exc:
            log.warning("radar_refresh.cycle_error", error=str(exc))

        await asyncio.sleep(settings.radar_refresh_interval)


def start_radar_refresh() -> "asyncio.Task[None]":
    """Spawn the radar-refresh loop as a named asyncio background task."""
    return asyncio.create_task(run_radar_refresh(), name="radar-refresh")


async def stop_radar_refresh(task: "asyncio.Task[None]") -> None:
    """Cancel the radar-refresh loop and wait for it to finish."""
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    log.info("radar_refresh.stopped")
