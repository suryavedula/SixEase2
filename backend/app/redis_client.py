"""Redis client wiring (TASK-005, EPIC-01).

Mirrors the `app/db.py` shape: one module-level async client plus a `ping_*()`
connectivity check used by the readiness probe. Adds two helper families that
later tasks consume unchanged:

- **Queues** (`enqueue`/`dequeue`) — backbone for the news poller/fan-out
  (TASK-029/030). FIFO via `LPUSH` + blocking `BRPOP`.
- **Cache** (`cache_set`/`cache_get`) — general key/value with optional TTL.

All payloads are JSON-encoded; the client runs with `decode_responses=True` so
reads come back as `str`.
"""

import json
from typing import Any

import redis.asyncio as redis

from app.config import get_settings
from app.logging import get_logger

settings = get_settings()
log = get_logger(__name__)

# Module-level singleton — import this rather than constructing a new client.
# `redis.asyncio` manages an internal connection pool; one client is shared
# process-wide and closed on lifespan shutdown.
redis_client: redis.Redis = redis.from_url(settings.redis_url, decode_responses=True)


async def ping_redis() -> bool:
    """Lightweight connectivity check used by the readiness probe."""
    return await redis_client.ping()


async def close_redis() -> None:
    """Release the connection pool on app shutdown (called from lifespan)."""
    await redis_client.aclose()


# --- Queue helpers ---------------------------------------------------------
async def enqueue(queue: str, payload: dict[str, Any]) -> None:
    """Push a JSON payload onto the head of `queue` (paired with `dequeue`)."""
    await redis_client.lpush(queue, json.dumps(payload))


async def dequeue(queue: str, timeout: int = 0) -> dict[str, Any] | None:
    """Blocking pop from the tail of `queue` (FIFO with `enqueue`).

    `timeout` is seconds to block; `0` blocks indefinitely. Returns the decoded
    payload, or `None` if the timeout elapses with nothing queued.
    """
    result = await redis_client.brpop([queue], timeout=timeout)
    if result is None:
        return None
    _, raw = result  # (queue_name, value)
    return json.loads(raw)


# --- Cache helpers ---------------------------------------------------------
async def cache_set(key: str, value: dict[str, Any], ttl: int | None = None) -> None:
    """Store a JSON value under `key`, optionally expiring after `ttl` seconds."""
    await redis_client.set(key, json.dumps(value), ex=ttl)


async def cache_get(key: str) -> dict[str, Any] | None:
    """Fetch and JSON-decode `key`, or `None` if absent/expired."""
    raw = await redis_client.get(key)
    return json.loads(raw) if raw is not None else None
