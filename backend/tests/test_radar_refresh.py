"""Unit tests for backend/app/radar_refresh.py (proactive radar layer).

All async I/O is mocked; no DB needed. Each test runs one cycle of
run_radar_refresh() by patching asyncio.sleep to stop the infinite loop, mirroring
tests/test_poller.py.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.radar_refresh import run_radar_refresh

_COUNTS = {"events_written": 12, "unresolved": 1}


def _patch_session(mock_sf):
    mock_sf.return_value.__aenter__ = AsyncMock(return_value=MagicMock())
    mock_sf.return_value.__aexit__ = AsyncMock(return_value=False)


@pytest.mark.asyncio
async def test_cycle_rebuilds_radar():
    """One cycle calls build_change_radar and then sleeps."""
    with (
        patch("app.radar_refresh.SessionFactory") as mock_sf,
        patch("app.radar_refresh.settings") as mock_settings,
        patch("app.radar_refresh.ingest_email_signals", new=AsyncMock(return_value=[])) as mock_email,
        patch("app.radar_refresh.build_change_radar", new=AsyncMock(return_value=_COUNTS)) as mock_build,
        patch("app.radar_refresh.asyncio.sleep", new=AsyncMock(side_effect=StopAsyncIteration)),
    ):
        mock_settings.ms_graph_enabled = False
        mock_settings.radar_refresh_interval = 300
        _patch_session(mock_sf)
        with pytest.raises(StopAsyncIteration):
            await run_radar_refresh()

    mock_build.assert_called_once()
    # email signals skipped when Graph is not configured
    mock_email.assert_not_called()


@pytest.mark.asyncio
async def test_cycle_folds_email_when_graph_enabled():
    """When MS Graph is configured, email signals are fetched and passed through."""
    signals = [{"x": 1}]
    with (
        patch("app.radar_refresh.SessionFactory") as mock_sf,
        patch("app.radar_refresh.settings") as mock_settings,
        patch("app.radar_refresh.ingest_email_signals", new=AsyncMock(return_value=signals)) as mock_email,
        patch("app.radar_refresh.build_change_radar", new=AsyncMock(return_value=_COUNTS)) as mock_build,
        patch("app.radar_refresh.asyncio.sleep", new=AsyncMock(side_effect=StopAsyncIteration)),
    ):
        mock_settings.ms_graph_enabled = True
        mock_settings.radar_refresh_interval = 300
        _patch_session(mock_sf)
        with pytest.raises(StopAsyncIteration):
            await run_radar_refresh()

    mock_email.assert_called_once()
    assert mock_build.call_args.kwargs["extra_signals"] == signals


@pytest.mark.asyncio
async def test_exception_does_not_kill_loop():
    """A transient rebuild error is caught; the loop continues to the next sleep."""
    sleep_calls = 0

    async def _counting_sleep(_delay):
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls >= 2:
            raise StopAsyncIteration

    with (
        patch("app.radar_refresh.SessionFactory") as mock_sf,
        patch("app.radar_refresh.settings") as mock_settings,
        patch("app.radar_refresh.ingest_email_signals", new=AsyncMock(return_value=[])),
        patch(
            "app.radar_refresh.build_change_radar",
            new=AsyncMock(side_effect=RuntimeError("db hiccup")),
        ),
        patch("app.radar_refresh.asyncio.sleep", new=_counting_sleep),
    ):
        mock_settings.ms_graph_enabled = False
        mock_settings.radar_refresh_interval = 300
        _patch_session(mock_sf)
        with pytest.raises(StopAsyncIteration):
            await run_radar_refresh()

    assert sleep_calls == 2
