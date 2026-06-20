"""Unit tests for backend/app/poller.py (TASK-029).

All async I/O is mocked; no Redis or database needed. Each test exercises one
cycle of run_poller() by patching asyncio.sleep to raise after the first call
so the infinite loop terminates cleanly.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, call, patch

import pytest

from app.news import NewsArticle
from app.poller import run_poller

# ---------------------------------------------------------------------------
# Shared test fixtures
# ---------------------------------------------------------------------------

_ARTICLE = NewsArticle(
    uri="art-1",
    title="Markets rally on Fed news",
    body="The market moved sharply...",
    url="https://example.com/1",
    source="Reuters",
    published_at="2026-06-20T09:00:00Z",
    sentiment=0.4,
)

_INDEX_WITH_KEYWORDS = {"keywords": ["Novartis", "healthcare"], "client_count": 2, "keyword_count": 2}
_INDEX_EMPTY = {"keywords": [], "client_count": 0, "keyword_count": 0}


def _make_sleep_stopper():
    """Return an AsyncMock for asyncio.sleep that raises StopAsyncIteration on the first call."""
    async def _stop(*_args, **_kwargs):
        raise StopAsyncIteration

    return _stop


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bootstrap_no_cursor():
    """With no saved cursor, get_recent_activity is called with cursor=None."""
    with (
        patch("app.poller.SessionFactory") as mock_sf,
        patch("app.poller.get_global_index", new=AsyncMock(return_value=_INDEX_WITH_KEYWORDS)),
        patch("app.poller.cache_get", new=AsyncMock(return_value=None)),
        patch("app.poller.get_recent_activity", new=AsyncMock(return_value=([], None))) as mock_poll,
        patch("app.poller.cache_set", new=AsyncMock()),
        patch("app.poller.enqueue", new=AsyncMock()),
        patch("app.poller.asyncio.sleep", new=AsyncMock(side_effect=StopAsyncIteration)),
    ):
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(StopAsyncIteration):
            await run_poller()

    mock_poll.assert_called_once()
    _, kwargs = mock_poll.call_args
    assert kwargs.get("keywords") == _INDEX_WITH_KEYWORDS["keywords"]
    # First positional arg is the cursor
    assert mock_poll.call_args[0][0] is None


@pytest.mark.asyncio
async def test_cursor_advance():
    """After a successful cycle, the new cursor is persisted to Redis."""
    new_cursor = "cursor-xyz"
    with (
        patch("app.poller.SessionFactory") as mock_sf,
        patch("app.poller.get_global_index", new=AsyncMock(return_value=_INDEX_WITH_KEYWORDS)),
        patch("app.poller.cache_get", new=AsyncMock(return_value={"cursor": "old-cursor"})),
        patch("app.poller.get_recent_activity", new=AsyncMock(return_value=([], new_cursor))),
        patch("app.poller.cache_set", new=AsyncMock()) as mock_cache_set,
        patch("app.poller.enqueue", new=AsyncMock()),
        patch("app.poller.asyncio.sleep", new=AsyncMock(side_effect=StopAsyncIteration)),
    ):
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(StopAsyncIteration):
            await run_poller()

    mock_cache_set.assert_called_once_with("news:cursor", {"cursor": new_cursor})


@pytest.mark.asyncio
async def test_articles_enqueued():
    """Each article returned by the feed is pushed to the news:candidates queue."""
    articles = [_ARTICLE, _ARTICLE]
    with (
        patch("app.poller.SessionFactory") as mock_sf,
        patch("app.poller.get_global_index", new=AsyncMock(return_value=_INDEX_WITH_KEYWORDS)),
        patch("app.poller.cache_get", new=AsyncMock(return_value=None)),
        patch("app.poller.get_recent_activity", new=AsyncMock(return_value=(articles, "c1"))),
        patch("app.poller.cache_set", new=AsyncMock()),
        patch("app.poller.enqueue", new=AsyncMock()) as mock_enqueue,
        patch("app.poller.asyncio.sleep", new=AsyncMock(side_effect=StopAsyncIteration)),
    ):
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(StopAsyncIteration):
            await run_poller()

    assert mock_enqueue.call_count == 2
    for c in mock_enqueue.call_args_list:
        assert c == call("news:candidates", _ARTICLE.model_dump())


@pytest.mark.asyncio
async def test_empty_feed_no_enqueue():
    """When the feed returns no articles, enqueue is never called."""
    with (
        patch("app.poller.SessionFactory") as mock_sf,
        patch("app.poller.get_global_index", new=AsyncMock(return_value=_INDEX_WITH_KEYWORDS)),
        patch("app.poller.cache_get", new=AsyncMock(return_value=None)),
        patch("app.poller.get_recent_activity", new=AsyncMock(return_value=([], "c1"))),
        patch("app.poller.cache_set", new=AsyncMock()),
        patch("app.poller.enqueue", new=AsyncMock()) as mock_enqueue,
        patch("app.poller.asyncio.sleep", new=AsyncMock(side_effect=StopAsyncIteration)),
    ):
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(StopAsyncIteration):
            await run_poller()

    mock_enqueue.assert_not_called()


@pytest.mark.asyncio
async def test_empty_keywords_skips_api():
    """When the global watchlist is empty, the API is not called — only sleep."""
    with (
        patch("app.poller.SessionFactory") as mock_sf,
        patch("app.poller.get_global_index", new=AsyncMock(return_value=_INDEX_EMPTY)),
        patch("app.poller.cache_get", new=AsyncMock()),
        patch("app.poller.get_recent_activity", new=AsyncMock()) as mock_poll,
        patch("app.poller.enqueue", new=AsyncMock()),
        patch("app.poller.asyncio.sleep", new=AsyncMock(side_effect=StopAsyncIteration)),
    ):
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(StopAsyncIteration):
            await run_poller()

    mock_poll.assert_not_called()


@pytest.mark.asyncio
async def test_exception_does_not_kill_loop():
    """A transient error in a poll cycle is caught; the loop continues to sleep."""
    sleep_calls = 0

    async def _counting_sleep(_delay):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            raise StopAsyncIteration

    with (
        patch("app.poller.SessionFactory") as mock_sf,
        patch("app.poller.get_global_index", new=AsyncMock(return_value=_INDEX_WITH_KEYWORDS)),
        patch("app.poller.cache_get", new=AsyncMock(return_value=None)),
        patch(
            "app.poller.get_recent_activity",
            new=AsyncMock(side_effect=RuntimeError("Event Registry 429")),
        ),
        patch("app.poller.enqueue", new=AsyncMock()),
        patch("app.poller.asyncio.sleep", new=_counting_sleep),
    ):
        mock_sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
        mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)

        with pytest.raises(StopAsyncIteration):
            await run_poller()

    # sleep was called twice — the loop survived the first-cycle exception
    assert sleep_calls == 2
