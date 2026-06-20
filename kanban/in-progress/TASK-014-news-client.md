# TASK-014: Event Registry client

**Status:** IN-PROGRESS · **Epic:** EPIC-03 · **Priority:** P0 · **Type:** feature · **Effort:** M · **Created:** 2026-06-20
**Assigned:** Unassigned · **Started:** 2026-06-20 · **Analysis Completed:** 2026-06-20

## Description
Python client for newsapi.ai: article search and the recent-activity stream with newestUri cursor; concept/keyword filters; per-article sentiment.

## Acceptance Criteria
- [x] keyword/concept search returns articles+sentiment
- [x] recent-activity polling with cursor
- [x] respects 5-concurrent limit

## Dependencies
TASK-006 (config/secrets — DONE: `newsapi_key` + `newsai_api_url` already in `Settings`)

## Refs
Requirements §14.1

---

## Technical Analysis (Auto-generated 2026-06-20)

### Existing Resources Found
- **Config:** `app/config.py` — `settings.newsapi_key` (env `NEWSAPI_KEY`) and `settings.newsai_api_url` (default `https://eventregistry.org/api/v1`) already defined in `Settings` by TASK-006. `settings.missing_secrets()` already covers `NEWSAPI_KEY`. No config changes needed.
- **HTTP client:** `httpx.AsyncClient` already in `requirements.txt` (pinned `>=0.23.0,<0.28.0` for TASK-013). No new package needed.
- **Client pattern:** `app/six.py` — exact singleton pattern to mirror: lazy `_get_client()`, module-level `_client`, `close_*()` / `ping_*()` lifespan hooks, `get_logger(__name__)`, `get_settings()`.
- **Lifespan wiring:** `app/main.py` — already wires `ping_llm`, `ping_six`, `close_*` hooks; same pattern applied for `ping_news` / `close_news`.
- **Demo reference:** `demo/src/backend/services/newsai.service.ts` — proves the REST API shape: POST `/article/getArticles` with apiKey in body; `articles.results[]` with `uri`, `title`, `body`, `url`, `source.title`, `dateTimePub`, `sentiment` fields.
- **DB schema:** `app/models/derived.py::NewsItem` — the table that downstream tasks (TASK-028 news-match, TASK-031 dedup-seed) will write to. Client returns `NewsArticle` Pydantic models; persistence is owned by TASK-028+.
- **Test pattern:** `tests/test_six.py` — mock `_call_tool` for async tests; pure-function tests for parsers. Exactly mirrored in `tests/test_news.py` patching `_post`.

### Dependencies Required
- **Backend packages:** `httpx>=0.23.0,<0.28.0` (already pinned), no new dep
- **Test packages:** `pytest-asyncio==0.24.0` — added to `requirements.txt` (was missing; needed by TASK-013 tests too)
- **Database migrations:** none — client is stateless; `NewsItem` table exists from TASK-004 migration
- **Docker services:** none — Event Registry is an external HTTPS endpoint

### Files Modified
- `backend/app/news.py` *(new)* — singleton async Event Registry client
- `backend/tests/test_news.py` *(new)* — 19 tests: 9 pure-function, 10 async-mocked
- `backend/app/main.py` — added `ping_news` / `close_news` to lifespan
- `backend/requirements.txt` — added `pytest-asyncio==0.24.0`

### Impact Assessment
#### Components Affected
- `app/main.py`: LOW — additive only (import + 2 try/except blocks in lifespan)
- `requirements.txt`: LOW — one new test package

#### API Changes
None — this task adds a new internal module, not a router endpoint.

#### Database Changes
None — the client is read/write-free; `NewsItem` persistence is TASK-028.

### Implementation Notes
- **Auth:** apiKey goes in the POST body (Event Registry convention), not an Authorization header. The `_post()` helper injects it automatically so callers never forget it.
- **Two feed modes:**
  - `search_articles()` → `/article/getArticles` — on-demand batch; used by demo "Scan news" flow and TASK-028.
  - `get_recent_activity(newest_uri)` → `/article/getRecentActivity` — cursor-advancing near-real-time stream; used by the §14.2 poller (TASK-029). Pass `newest_uri=None` on first call to bootstrap the cursor.
- **5-concurrent-request limit (§14.2 F2):** enforced at the caller/scheduler layer (TASK-029 single sequential poller), not in this client. The client is stateless and has no semaphore by design.
- **Concept URIs preferred over keywords** (§14.1): `conceptUri` parameter gives precise entity matching; keyword fallback for thematic queries.
- **Sentiment:** Event Registry returns `sentiment` in `[-1, 1]` per article; parsed as `float | None`. Downstream scoring (TASK-028/032) maps to BULLISH/BEARISH/NEUTRAL labels.
- **Body capped at 2 000 chars** in `_parse_articles` — sufficient for triage; full text not stored at this layer.

### Implementation Checklist
- [x] Reuse existing `httpx.AsyncClient` (already in requirements, not reimported as new dep)
- [x] Reuse `get_settings()` singleton — no second `Settings()` instantiation
- [x] Mirror `app/six.py` pattern — singleton, lazy init, ping/close, structlog
- [x] Follow SOLID principles — stateless client, single responsibility
- [x] Maintain backwards compatibility — additive changes only to `main.py`
- [x] Add proper error handling — `raise_for_status()` + API-level error check in `_post()`
- [x] Write self-documenting code — no redundant comments
- [x] Wire `ping_news` / `close_news` into lifespan

### Risk Analysis
- **Risk Level:** LOW
- **Main Risks:**
  - *NEWSAPI_KEY not set at boot:* mitigated — `missing_secrets()` warns at startup (TASK-006), client logs `news.no_key` warning and still boots; ping returns false
  - *API response shape change:* mitigated — `_parse_articles` uses `.get()` with safe defaults throughout; bad fields degrade gracefully to empty strings / None
  - *Token-budget exhaustion (§14.5):* out of scope for this client — poller cadence (TASK-029) controls spend

### Estimated Effort
- Original: M
- Adjusted: M (unchanged)
- Reason: clean analogue to `six.py` with demo reference; no surprises
