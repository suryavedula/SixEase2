"""Unit tests for backend/app/loaders/alert_noise.py (TASK-033, EPIC-08)."""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.loaders.alert_noise import (
    _fyi_label,
    _make_cooldown_key,
    build_needs_attention,
    passes_threshold,
    record_cooldown,
    should_suppress,
)


# ---------------------------------------------------------------------------
# passes_threshold — pure function
# ---------------------------------------------------------------------------


def test_passes_threshold_above():
    assert passes_threshold(0.15, 0.10) is True


def test_passes_threshold_at_boundary():
    # strictly greater-than — boundary value does NOT pass
    assert passes_threshold(0.10, 0.10) is False


def test_passes_threshold_below():
    assert passes_threshold(0.05, 0.10) is False


def test_passes_threshold_negative():
    assert passes_threshold(-0.5, 0.10) is False


def test_passes_threshold_zero_threshold():
    assert passes_threshold(0.01, 0.0) is True


def test_passes_threshold_both_zero():
    assert passes_threshold(0.0, 0.0) is False


# ---------------------------------------------------------------------------
# _make_cooldown_key — pure function
# ---------------------------------------------------------------------------

_CID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def test_make_cooldown_key_prefix():
    key = _make_cooldown_key(_CID, "drift_breach", "Equities CH")
    assert key.startswith("alert:cd:")


def test_make_cooldown_key_contains_class():
    key = _make_cooldown_key(_CID, "stale_sell", "CH1234567890")
    assert "stale_sell" in key
    assert "CH1234567890" in key


def test_make_cooldown_key_deterministic():
    k1 = _make_cooldown_key(_CID, "panic", "some-cluster")
    k2 = _make_cooldown_key(_CID, "panic", "some-cluster")
    assert k1 == k2


def test_make_cooldown_key_different_classes():
    k1 = _make_cooldown_key(_CID, "drift_breach", "Bonds CH")
    k2 = _make_cooldown_key(_CID, "stale_sell", "Bonds CH")
    assert k1 != k2


# ---------------------------------------------------------------------------
# _fyi_label — pure function
# ---------------------------------------------------------------------------


def test_fyi_label_known_class_plural():
    assert _fyi_label("good_news", 3) == "3 good news items"


def test_fyi_label_known_class_singular():
    assert _fyi_label("overdue_promise", 1) == "1 open promise"


def test_fyi_label_unknown_class():
    label = _fyi_label("custom_class", 2)
    assert "2" in label
    assert "custom_class" in label


def test_fyi_label_none_class():
    label = _fyi_label(None, 5)
    assert "5" in label


# ---------------------------------------------------------------------------
# should_suppress — async
# ---------------------------------------------------------------------------

_CLIENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


@pytest.mark.asyncio
async def test_should_suppress_cooldown_hit():
    """Redis hit → suppress; no further work."""
    with patch(
        "app.loaders.alert_noise.cache_get",
        new=AsyncMock(return_value={"fired": 1}),
    ):
        result = await should_suppress(_CLIENT_ID, "drift_breach", "Bonds CH")
    assert result is True


@pytest.mark.asyncio
async def test_should_suppress_cache_miss():
    """Redis miss → do not suppress."""
    with patch(
        "app.loaders.alert_noise.cache_get",
        new=AsyncMock(return_value=None),
    ):
        result = await should_suppress(_CLIENT_ID, "stale_sell", "US1234567890")
    assert result is False


@pytest.mark.asyncio
async def test_should_suppress_redis_error_fails_open():
    """Redis error → fail open (return False) so outage never silences alerts."""
    with patch(
        "app.loaders.alert_noise.cache_get",
        new=AsyncMock(side_effect=ConnectionError("redis down")),
    ):
        result = await should_suppress(_CLIENT_ID, "panic", "cluster-abc")
    assert result is False


# ---------------------------------------------------------------------------
# record_cooldown — async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_record_cooldown_writes_correct_key():
    cid = uuid.UUID("00000000-0000-0000-0000-000000000003")
    with patch(
        "app.loaders.alert_noise.cache_set",
        new=AsyncMock(),
    ) as mock_set:
        await record_cooldown(cid, "stale_sell", "US4581401001")

    mock_set.assert_awaited_once()
    args, kwargs = mock_set.call_args
    key, value = args[0], args[1]
    ttl = kwargs.get("ttl", args[2] if len(args) > 2 else None)
    assert "stale_sell" in key
    assert "US4581401001" in key
    assert value == {"fired": 1}
    assert ttl == 86_400


@pytest.mark.asyncio
async def test_record_cooldown_redis_error_does_not_raise():
    """A Redis write failure must not crash the caller."""
    with patch(
        "app.loaders.alert_noise.cache_set",
        new=AsyncMock(side_effect=ConnectionError("redis down")),
    ):
        await record_cooldown(_CLIENT_ID, "drift_breach", "Equities CH")
    # No exception raised — test passes


# ---------------------------------------------------------------------------
# build_needs_attention — async
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_needs_attention_empty():
    """No open alerts → all counts zero, empty fyi_groups."""
    mock_session = MagicMock()
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await build_needs_attention(mock_session, _CLIENT_ID)

    assert result["critical_count"] == 0
    assert result["attention_count"] == 0
    assert result["fyi_groups"] == []
    assert result["total_open"] == 0
    assert result["client_id"] == str(_CLIENT_ID)


@pytest.mark.asyncio
async def test_build_needs_attention_counts_severities():
    """CRITICAL and ATTENTION rows are counted; FYI rows go to fyi_groups."""
    from app.models.enums import Severity

    mock_session = MagicMock()
    row_critical = MagicMock(alert_class="drift_breach", severity=Severity.CRITICAL, cnt=2)
    row_attention = MagicMock(alert_class="stale_sell", severity=Severity.ATTENTION, cnt=3)
    row_fyi = MagicMock(alert_class="good_news", severity=Severity.FYI, cnt=4)
    mock_result = MagicMock()
    mock_result.all.return_value = [row_critical, row_attention, row_fyi]
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await build_needs_attention(mock_session, _CLIENT_ID)

    assert result["critical_count"] == 2
    assert result["attention_count"] == 3
    assert result["total_open"] == 9
    assert len(result["fyi_groups"]) == 1
    assert result["fyi_groups"][0]["alert_class"] == "good_news"
    assert result["fyi_groups"][0]["count"] == 4


@pytest.mark.asyncio
async def test_build_needs_attention_fyi_sorted_by_count():
    """FYI groups are sorted descending by count."""
    from app.models.enums import Severity

    mock_session = MagicMock()
    rows = [
        MagicMock(alert_class="values_drift", severity=Severity.FYI, cnt=1),
        MagicMock(alert_class="good_news", severity=Severity.FYI, cnt=5),
        MagicMock(alert_class="overdue_promise", severity=Severity.FYI, cnt=3),
    ]
    mock_result = MagicMock()
    mock_result.all.return_value = rows
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await build_needs_attention(mock_session, _CLIENT_ID)

    counts = [g["count"] for g in result["fyi_groups"]]
    assert counts == sorted(counts, reverse=True)
    assert counts[0] == 5


@pytest.mark.asyncio
async def test_build_needs_attention_severity_as_string():
    """Handles severity stored as a plain string (not enum member)."""
    mock_session = MagicMock()
    row = MagicMock()
    row.alert_class = "drift_breach"
    row.severity = "Critical"  # string, not enum
    row.cnt = 1
    mock_result = MagicMock()
    mock_result.all.return_value = [row]
    mock_session.execute = AsyncMock(return_value=mock_result)

    result = await build_needs_attention(mock_session, _CLIENT_ID)

    assert result["critical_count"] == 1
