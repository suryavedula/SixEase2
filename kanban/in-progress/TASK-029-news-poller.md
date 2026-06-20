# TASK-029: Firehose-filter poller

**Status:** IN-PROGRESS · **Epic:** EPIC-07 · **Priority:** P1 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Single sequential poller over the recent-activity feed filtered to the global watchlist, advancing the newestUri cursor; enqueue matched candidates to Redis. Respects the 5-concurrent limit.

## Acceptance Criteria
- [ ] gapless polling via cursor
- [ ] filtered to global watchlist
- [ ] candidates queued to Redis

## Dependencies
TASK-014 ✅, TASK-027 ✅, TASK-005 ✅

## Refs
Requirements §14.2 F1/F2

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found
- **`app/news.py`** — `get_recent_activity(newest_uri, *, keywords, ...) → (list[NewsArticle], str|None)`: cursor-advancing feed call already built (TASK-014). The sequential poller simply calls this in a loop.
- **`app/redis_client.py`** — `enqueue(queue, payload)`, `cache_set(key, value, ttl)`, `cache_get(key)`: queue backbone and cursor persistence are ready (TASK-005).
- **`app/loaders/watchlist.py`** — `get_global_index(session) → {"keywords": [...], "client_count": N, "keyword_count": N}`: global union of all clients' keywords is ready (TASK-027).
- **`app/db.py`** — `SessionFactory`: async session maker for creating non-request-scoped sessions in background tasks.
- **`app/config.py`** — `newsapi_key`, `newsai_api_url` already wired into settings.
- **`app/main.py`** — lifespan context already starts/stops Redis, News, LLM, SIX. Pattern to follow for the poller task.

### Dependencies Required
- Frontend packages: None
- Backend packages: None (all in existing requirements — `redis`, `httpx`, `sqlalchemy`)
- Database migrations: None (uses existing `client_watchlists` table + Redis)
- Docker services: Redis (running), Postgres (running)

### Impact Assessment

#### Files to Create
- `backend/app/poller.py`: the poller module — `run_poller()` loop + `start_poller()` / `stop_poller()` lifecycle handles

#### Files to Modify
- `backend/app/config.py`: add `news_poll_interval: int = Field(default=300)` (5-min default per §14.3)
- `backend/app/main.py`: wire `start_poller()` / `stop_poller()` into lifespan (same pattern as `ping_news` / `close_news`)

#### Components Affected
- `app/main.py`: LOW — one `asyncio.create_task` call in lifespan, one cancel on shutdown
- `app/config.py`: LOW — one new field with a safe default
- `app/news.py`: none — consumed as-is
- `app/redis_client.py`: none — consumed as-is
- `app/loaders/watchlist.py`: none — consumed as-is

#### API Changes
None — this is a background asyncio task with no HTTP surface.

#### Database Changes
None — reads `client_watchlists` (SELECT) via `get_global_index`; cursor persisted in Redis not Postgres.

### Key Design Decisions

**Queue name:** `news:candidates` — namespaced Redis key; TASK-028 (news-match) will dequeue from here.

**Cursor persistence:** `cache_set("news:cursor", {"cursor": value})` / `cache_get("news:cursor")` so the cursor survives app restarts (no cursor gap across redeploys).

**Error handling:** catch all exceptions per poll cycle, log the error, sleep the interval, then retry — never let a transient 429 or network error kill the background task.

**Watchlist refresh:** re-read `get_global_index()` once per cycle (inside the loop) so new clients / watchlist changes are picked up without a restart. One extra SELECT per interval is negligible.

**Payload shape enqueued to `news:candidates`:**
```json
{
  "uri": "...",
  "title": "...",
  "body": "...",
  "url": "...",
  "source": "...",
  "published_at": "...",
  "sentiment": 0.35
}
```
(flat dict from `NewsArticle.model_dump()`)

### Implementation Checklist
- [ ] Add `news_poll_interval: int = Field(default=300)` to `Settings` in `config.py`
- [ ] Create `backend/app/poller.py`:
  - `async def run_poller() -> None` — infinite loop: load index → poll feed → enqueue → persist cursor → sleep
  - `def start_poller() -> asyncio.Task` — `asyncio.create_task(run_poller())`
  - `def stop_poller(task: asyncio.Task) -> None` — `task.cancel()`
- [ ] Wire into `main.py` lifespan: store task in a module-level var, start after Redis is confirmed up, cancel on shutdown
- [ ] Write `backend/tests/test_poller.py`:
  - test cursor bootstrap (None → first cursor saved)
  - test cursor advance (old cursor passed to next call)
  - test articles enqueued as `NewsArticle.model_dump()`
  - test no enqueue on empty feed
  - test exception in poll cycle is caught (task does not die)
- [ ] Follow SOLID principles (poller is a thin orchestrator — no business logic)
- [ ] Maintain backwards compatibility (no schema changes)
- [ ] Include proper error handling (catch per-cycle, log, sleep, continue)

### Risk Analysis
- **Risk Level:** LOW–MEDIUM
- **Main Risks:**
  - **Event Registry 429 throttle:** mitigated by single sequential poller design (§14.2 F2) — only one concurrent request ever in flight; if a 429 occurs the exception is caught, logged, and the poller sleeps until the next interval
  - **Empty watchlist on first boot (no clients seeded yet):** mitigated by checking `len(keywords) == 0` and skipping the API call (log a warning, sleep, retry next cycle)
  - **Cursor loss on Redis restart:** acceptable for the hackathon; worst case is a small replay window on next bootstrap call

### Estimated Effort
- Original: M
- Adjusted: S–M
- Reason: all three dependency modules (news client, Redis helpers, global index) are fully implemented. This is a thin orchestration loop — ~60–80 lines of production code + ~40 lines of tests.
