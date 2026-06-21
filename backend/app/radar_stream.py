"""In-process pub/sub for the proactive radar SSE channel (EPIC-08).

The dispatch loop publishes each pushed change here; `GET /radar/stream`
subscribers forward them to the browser as Server-Sent Events. In-process (a set
of asyncio Queues) rather than Redis pub/sub, because the dispatch loop and the
API run in the same process — no extra dependency.

Best-effort: a slow or full subscriber queue drops the event for that subscriber
rather than blocking the publisher, so one stuck browser tab can't stall dispatch.
"""

import asyncio
import json
from typing import Any

from app.logging import get_logger

log = get_logger(__name__)

_subscribers: set[asyncio.Queue] = set()
_MAX_QUEUE = 100


def subscribe() -> asyncio.Queue:
    """Register a new SSE subscriber; returns its event queue (JSON strings)."""
    q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE)
    _subscribers.add(q)
    log.info("radar_stream.subscribed", subscribers=len(_subscribers))
    return q


def unsubscribe(q: asyncio.Queue) -> None:
    """Remove a subscriber (on disconnect)."""
    _subscribers.discard(q)
    log.info("radar_stream.unsubscribed", subscribers=len(_subscribers))


def publish(event: dict[str, Any]) -> int:
    """Fan a pushed change out to all subscribers. Returns the number reached."""
    data = json.dumps(event, default=str)
    reached = 0
    for q in list(_subscribers):
        try:
            q.put_nowait(data)
            reached += 1
        except asyncio.QueueFull:
            log.warning("radar_stream.subscriber_lagging_dropped")
    return reached


def subscriber_count() -> int:
    return len(_subscribers)
