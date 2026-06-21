"""Unit tests for backend/app/news.py (TASK-014).

Pure-function tests need no mocking. Async tests patch _post so no network
is required. Pattern mirrors tests/test_six.py.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.news import (
    NewsArticle,
    _parse_articles,
    get_recent_activity,
    ping_news,
    search_articles,
)


# ---------------------------------------------------------------------------
# _parse_articles — pure function
# ---------------------------------------------------------------------------

_FULL_ARTICLE = {
    "uri": "abc-123",
    "title": "Pharma giant cuts research budget",
    "body": "The company announced today…",
    "url": "https://example.com/article",
    "source": {"title": "Reuters"},
    "dateTimePub": "2026-06-20T10:00:00Z",
    "sentiment": 0.35,
}


def test_parse_articles_full():
    articles = _parse_articles([_FULL_ARTICLE])
    assert len(articles) == 1
    a = articles[0]
    assert isinstance(a, NewsArticle)
    assert a.uri == "abc-123"
    assert a.title == "Pharma giant cuts research budget"
    assert a.url == "https://example.com/article"
    assert a.source == "Reuters"
    assert a.published_at == "2026-06-20T10:00:00Z"
    assert a.sentiment == pytest.approx(0.35)


def test_parse_articles_empty_list():
    assert _parse_articles([]) == []


def test_parse_articles_no_sentiment():
    raw = {**_FULL_ARTICLE, "sentiment": None}
    articles = _parse_articles([raw])
    assert articles[0].sentiment is None


def test_parse_articles_sentiment_zero():
    raw = {**_FULL_ARTICLE, "sentiment": 0}
    articles = _parse_articles([raw])
    assert articles[0].sentiment == pytest.approx(0.0)


def test_parse_articles_missing_uri_fallback():
    raw = {**_FULL_ARTICLE, "uri": None}
    articles = _parse_articles([raw])
    assert articles[0].uri == "news-0"


def test_parse_articles_body_capped_at_2000():
    long_body = "x" * 3000
    raw = {**_FULL_ARTICLE, "body": long_body}
    articles = _parse_articles([raw])
    assert len(articles[0].body) == 2000


def test_parse_articles_fallback_datetime():
    raw = {**_FULL_ARTICLE, "dateTimePub": None, "dateTime": "2026-06-19T08:00:00Z"}
    articles = _parse_articles([raw])
    assert articles[0].published_at == "2026-06-19T08:00:00Z"


def test_parse_articles_missing_source():
    raw = {**_FULL_ARTICLE, "source": None}
    articles = _parse_articles([raw])
    assert articles[0].source == ""


def test_parse_articles_negative_sentiment():
    raw = {**_FULL_ARTICLE, "sentiment": -0.72}
    articles = _parse_articles([raw])
    assert articles[0].sentiment == pytest.approx(-0.72)


# ---------------------------------------------------------------------------
# search_articles — async, _post mocked
# ---------------------------------------------------------------------------

_SEARCH_RESPONSE = {
    "articles": {
        "results": [_FULL_ARTICLE],
    }
}


@pytest.mark.asyncio
async def test_search_articles_with_keywords():
    with patch("app.news._post", new=AsyncMock(return_value=_SEARCH_RESPONSE)) as mock_post:
        results = await search_articles(keywords=["pharma", "research"])
    assert len(results) == 1
    assert results[0].title == "Pharma giant cuts research budget"
    body = mock_post.call_args[0][1]
    assert body["keyword"] == ["pharma", "research"]
    assert body["keywordOper"] == "or"


@pytest.mark.asyncio
async def test_search_articles_with_concepts():
    with patch("app.news._post", new=AsyncMock(return_value=_SEARCH_RESPONSE)) as mock_post:
        results = await search_articles(concepts=["http://en.wikipedia.org/wiki/Novartis"])
    assert len(results) == 1
    body = mock_post.call_args[0][1]
    assert body["conceptUri"] == ["http://en.wikipedia.org/wiki/Novartis"]
    assert "keyword" not in body


@pytest.mark.asyncio
async def test_search_articles_empty_results():
    empty = {"articles": {"results": []}}
    with patch("app.news._post", new=AsyncMock(return_value=empty)):
        results = await search_articles(keywords=["nonexistent"])
    assert results == []


@pytest.mark.asyncio
async def test_search_articles_defaults_lang_and_count():
    with patch("app.news._post", new=AsyncMock(return_value=_SEARCH_RESPONSE)) as mock_post:
        await search_articles(keywords=["tech"])
    body = mock_post.call_args[0][1]
    assert body["lang"] == "eng"
    assert body["articlesCount"] == 20
    assert body["includeArticleSentiment"] is True


# ---------------------------------------------------------------------------
# get_recent_activity — async, _post mocked
# ---------------------------------------------------------------------------

# newestUri is returned by Event Registry as {"news": "<id>"}; the client
# normalises it to the bare id string.
_RECENT_RESPONSE = {
    "recentActivityArticles": {
        "newestUri": {"news": "new-cursor-xyz"},
        "activity": [_FULL_ARTICLE],
    }
}


@pytest.mark.asyncio
async def test_get_recent_activity_with_cursor():
    with patch("app.news._post", new=AsyncMock(return_value=_RECENT_RESPONSE)) as mock_post:
        articles, cursor = await get_recent_activity("old-cursor", keywords=["markets"])
    assert len(articles) == 1
    assert cursor == "new-cursor-xyz"
    endpoint, body = mock_post.call_args[0]
    assert endpoint == "/minuteStreamArticles"
    assert body["updatesAfterNewsUri"] == "old-cursor"


@pytest.mark.asyncio
async def test_get_recent_activity_bootstrap_no_cursor():
    with patch("app.news._post", new=AsyncMock(return_value=_RECENT_RESPONSE)) as mock_post:
        articles, cursor = await get_recent_activity(None)
    assert cursor == "new-cursor-xyz"
    body = mock_post.call_args[0][1]
    assert "updatesAfterNewsUri" not in body


@pytest.mark.asyncio
async def test_get_recent_activity_empty_feed():
    empty = {"recentActivityArticles": {"newestUri": {"news": "c1"}, "activity": []}}
    with patch("app.news._post", new=AsyncMock(return_value=empty)):
        articles, cursor = await get_recent_activity(None)
    assert articles == []
    assert cursor == "c1"


@pytest.mark.asyncio
async def test_get_recent_activity_no_cursor_in_response():
    no_cursor = {"recentActivityArticles": {"activity": [_FULL_ARTICLE]}}
    with patch("app.news._post", new=AsyncMock(return_value=no_cursor)):
        articles, cursor = await get_recent_activity("old")
    assert len(articles) == 1
    assert cursor is None


# ---------------------------------------------------------------------------
# ping_news — async, _post mocked
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ping_news_returns_true_on_success():
    ok = {"articles": {"results": []}}
    with patch("app.news._post", new=AsyncMock(return_value=ok)):
        assert await ping_news() is True


@pytest.mark.asyncio
async def test_ping_news_returns_false_on_http_error():
    with patch("app.news._post", new=AsyncMock(side_effect=Exception("timeout"))):
        assert await ping_news() is False
