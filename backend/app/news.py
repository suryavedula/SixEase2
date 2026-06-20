"""Event Registry / newsapi.ai client (TASK-014, EPIC-03).

REST client for https://eventregistry.org/api/v1. Singleton async httpx
client; public API covers the two feed modes described in §14:

  search_articles(keywords, concepts, ...)
      → list[NewsArticle]          (on-demand /article/getArticles)

  get_recent_activity(newest_uri, keywords, concepts, ...)
      → (list[NewsArticle], str|None)  (cursor-advancing /article/getRecentActivity)

  ping_news()   → bool   (lifespan health check)
  close_news()  → None   (lifespan shutdown)

Identifier conventions (§14.1):
  • Prefer `concepts` (Event Registry concept URIs) over `keywords` for precise
    entity matching — avoids name-collision false positives.
  • The caller is responsible for the 5-concurrent-request limit (§14.2 F2):
    the single sequential poller (TASK-029) enforces this at the scheduler level,
    not here, so the client stays stateless and testable.
  • Per-article sentiment is in [-1, 1]; None when the field is absent or null.
"""

from typing import Any

import httpx
from pydantic import BaseModel

from app.config import get_settings
from app.logging import get_logger

settings = get_settings()
log = get_logger(__name__)

_client: httpx.AsyncClient | None = None


# ---------------------------------------------------------------------------
# Public data models
# ---------------------------------------------------------------------------


class NewsArticle(BaseModel):
    uri: str
    title: str
    body: str        # capped at 2 000 chars; full text not needed for triage
    url: str
    source: str
    published_at: str  # ISO-8601 string from Event Registry
    sentiment: float | None  # [-1, 1]; None when absent in the payload


# ---------------------------------------------------------------------------
# Singleton client
# ---------------------------------------------------------------------------


def _get_client() -> httpx.AsyncClient:
    """Lazy singleton — built once from settings, reused process-wide."""
    global _client
    if _client is None:
        if not settings.newsapi_key:
            log.warning("news.no_key", hint="set NEWSAPI_KEY to enable Event Registry")
        _client = httpx.AsyncClient(
            base_url=settings.newsai_api_url,
            headers={"Content-Type": "application/json"},
            timeout=20.0,
        )
        log.info("news.init", url=settings.newsai_api_url)
    return _client


async def close_news() -> None:
    """Release the HTTP connection pool on app shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
        log.info("news.closed")


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


async def _post(endpoint: str, body: dict[str, Any]) -> dict[str, Any]:
    """POST to an Event Registry endpoint; raises ValueError on API errors.

    The apiKey goes in the request body (Event Registry convention — it is NOT
    a bearer-token header). Body fields are merged so callers never forget it.
    """
    client = _get_client()
    resp = await client.post(endpoint, json={**body, "apiKey": settings.newsapi_key})
    resp.raise_for_status()
    data: dict[str, Any] = resp.json()
    if data.get("error"):
        raise ValueError(f"[News] API error: {data['error']}")
    return data


def _parse_articles(results: list[dict[str, Any]]) -> list[NewsArticle]:
    """Map raw Event Registry article dicts to NewsArticle models.

    Pure function — no I/O, safe to test without mocking.
    """
    articles: list[NewsArticle] = []
    for i, a in enumerate(results):
        raw_sentiment = a.get("sentiment")
        articles.append(
            NewsArticle(
                uri=str(a.get("uri") or f"news-{i}"),
                title=a.get("title") or "",
                body=(a.get("body") or "")[:2000],
                url=a.get("url") or "",
                source=((a.get("source") or {}).get("title") or ""),
                published_at=a.get("dateTimePub") or a.get("dateTime") or "",
                sentiment=(
                    float(raw_sentiment)
                    if isinstance(raw_sentiment, (int, float))
                    else None
                ),
            )
        )
    return articles


# ---------------------------------------------------------------------------
# Public async API
# ---------------------------------------------------------------------------


async def search_articles(
    *,
    keywords: list[str] | None = None,
    concepts: list[str] | None = None,
    lang: str = "eng",
    count: int = 20,
) -> list[NewsArticle]:
    """On-demand article search via /article/getArticles.

    `concepts` are Event Registry concept URIs and are more precise than
    keyword strings (preferred for issuer/entity matching, §14.1).
    `keywords` are space-joined and matched with OR logic as a fallback.
    At least one of keywords or concepts must be non-empty.
    """
    body: dict[str, Any] = {
        "resultType": "articles",
        "dataType": ["news"],
        "lang": lang,
        "articlesCount": count,
        "articlesSortBy": "date",
        "includeArticleSentiment": True,
    }
    if keywords:
        body["keyword"] = " ".join(keywords)
        body["keywordOper"] = "or"
    if concepts:
        body["conceptUri"] = concepts
    data = await _post("/article/getArticles", body)
    results: list[dict[str, Any]] = (data.get("articles") or {}).get("results") or []
    log.info("news.search", keyword_count=len(keywords or []), concept_count=len(concepts or []), results=len(results))
    return _parse_articles(results)


async def get_recent_activity(
    newest_uri: str | None,
    *,
    keywords: list[str] | None = None,
    concepts: list[str] | None = None,
    lang: str = "eng",
    count: int = 100,
) -> tuple[list[NewsArticle], str | None]:
    """Poll the near-real-time feed, advancing the newestUri cursor.

    Pass newest_uri=None on the first call to bootstrap; subsequent calls
    pass the cursor returned by the previous call for gapless, duplicate-free
    coverage (§14.1). Returns (articles, new_newest_uri).

    Caller is responsible for enforcing the 5-concurrent-request limit (§14.2
    F2) — the single sequential poller design (TASK-029) handles this.
    """
    body: dict[str, Any] = {
        "lang": lang,
        "articlesCount": count,
        "includeArticleSentiment": True,
    }
    if newest_uri:
        body["updatesAfterNewsUri"] = newest_uri
    if keywords:
        body["keyword"] = " ".join(keywords)
        body["keywordOper"] = "or"
    if concepts:
        body["conceptUri"] = concepts
    data = await _post("/article/getRecentActivity", body)
    feed: dict[str, Any] = data.get("recentActivityArticles") or {}
    articles = _parse_articles(feed.get("activity") or [])
    new_cursor: str | None = feed.get("newestUri") or None
    log.info("news.recent_activity", fetched=len(articles), new_cursor=new_cursor)
    return articles, new_cursor


async def ping_news() -> bool:
    """Lightweight connectivity check — a minimal getArticles request."""
    try:
        await _post(
            "/article/getArticles",
            {
                "keyword": "markets",
                "articlesCount": 1,
                "resultType": "articles",
                "dataType": ["news"],
            },
        )
        return True
    except Exception as exc:
        log.warning("news.ping_failed", url=settings.newsai_api_url, error=str(exc))
        return False
