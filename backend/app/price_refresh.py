"""SIX price-watch background loop (EPIC-08 — the proactive layer).

Periodically scans held instruments via SIX and emits price-move / bond-maturity
Alert rows (see loaders/price_watch.py). SIX is JSON-RPC, not token-billed, so this
loop spends zero hosted-LLM (Phoeniqs) budget — the cheapest proactive axis. The
radar-refresh loop then folds the emitted alerts into change_events on its own
cadence, and the dispatch loop pushes them to the RM.

Disabled (a no-op loop) unless `price_watch_enabled` and a SIX token are set.

Usage (from main.py lifespan):
    task = start_price_watch()      # startup
    await stop_price_watch(task)    # shutdown
"""

import asyncio
import contextlib

from app.config import get_settings
from app.db import SessionFactory
from app.loaders.price_watch import scan_price_signals
from app.logging import get_logger

settings = get_settings()
log = get_logger(__name__)


async def run_price_watch() -> None:
    """Infinite loop: scan SIX for price/maturity signals, then sleep one interval."""
    if not settings.price_watch_enabled:
        log.info("price_watch.disabled", reason="price_watch_enabled is false")
        return
    if not settings.six_mcp_token:
        log.warning("price_watch.disabled", reason="SIX_MCP_TOKEN unset")
        return

    log.info("price_watch.started", interval=settings.price_watch_interval)
    while True:
        try:
            async with SessionFactory() as session:
                counts = await scan_price_signals(session)
            log.info("price_watch.cycle", **counts)
        except asyncio.CancelledError:
            raise  # propagate so stop_price_watch() can await cleanly
        except Exception as exc:
            log.warning("price_watch.cycle_error", error=str(exc))

        await asyncio.sleep(settings.price_watch_interval)


def start_price_watch() -> "asyncio.Task[None]":
    """Spawn the price-watch loop as a named asyncio background task."""
    return asyncio.create_task(run_price_watch(), name="price-watch")


async def stop_price_watch(task: "asyncio.Task[None]") -> None:
    """Cancel the price-watch loop and wait for it to finish."""
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    log.info("price_watch.stopped")
