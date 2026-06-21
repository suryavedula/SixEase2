"""Unit tests for the proactive layer (EPIC-08):

  • llm.py token budget guard (Piece 1)
  • loaders/price_watch.py price-move detection (Piece 2)
  • radar_dispatch.py quiet hours + dispatch dedup (Piece 3)

All network-free: Redis, SIX, SMTP and the DB session are mocked.
"""

import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import app.llm as llm
import app.loaders.price_watch as pw
import app.radar_dispatch as rd
from app.llm import BudgetExhausted, _budget_check, _budget_record, budget_status
from app.loaders.price_watch import _check_price_move
from app.radar_dispatch import is_quiet_hour, run_dispatch_cycle


# ---------------------------------------------------------------------------
# Piece 1 — token budget guard
# ---------------------------------------------------------------------------


def _fake_redis(get_value=None):
    fake = MagicMock()
    fake.get = AsyncMock(return_value=get_value)
    fake.incrby = AsyncMock(return_value=0)
    fake.expire = AsyncMock()
    return fake


@pytest.mark.asyncio
async def test_budget_check_raises_over_cap(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_provider", "phoeniqs")
    monkeypatch.setattr(llm.settings, "phoeniqs_budget_tokens", 1000)
    monkeypatch.setattr(llm, "redis_client", _fake_redis(get_value="1500"))
    with pytest.raises(BudgetExhausted):
        await _budget_check()


@pytest.mark.asyncio
async def test_budget_check_under_cap_is_ok(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_provider", "phoeniqs")
    monkeypatch.setattr(llm.settings, "phoeniqs_budget_tokens", 1000)
    monkeypatch.setattr(llm, "redis_client", _fake_redis(get_value="500"))
    await _budget_check()  # must not raise


@pytest.mark.asyncio
async def test_budget_check_ollama_never_metered(monkeypatch):
    # Local provider: even an absurd cap + spend never gates.
    monkeypatch.setattr(llm.settings, "llm_provider", "ollama")
    monkeypatch.setattr(llm.settings, "phoeniqs_budget_tokens", 1)
    monkeypatch.setattr(llm, "redis_client", _fake_redis(get_value="999999"))
    await _budget_check()  # must not raise


@pytest.mark.asyncio
async def test_budget_check_disabled_when_cap_zero(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_provider", "phoeniqs")
    monkeypatch.setattr(llm.settings, "phoeniqs_budget_tokens", 0)  # unlimited
    monkeypatch.setattr(llm, "redis_client", _fake_redis(get_value="999999"))
    await _budget_check()  # must not raise


@pytest.mark.asyncio
async def test_budget_record_increments_metered(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_provider", "phoeniqs")
    monkeypatch.setattr(llm.settings, "phoeniqs_budget_tokens", 10_000)
    fake = _fake_redis()
    fake.incrby = AsyncMock(return_value=512)
    monkeypatch.setattr(llm, "redis_client", fake)
    await _budget_record(512)
    fake.incrby.assert_awaited_once()
    fake.expire.assert_awaited_once()


@pytest.mark.asyncio
async def test_budget_record_skips_local(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_provider", "ollama")
    fake = _fake_redis()
    monkeypatch.setattr(llm, "redis_client", fake)
    await _budget_record(512)
    fake.incrby.assert_not_awaited()


@pytest.mark.asyncio
async def test_budget_status_shape(monkeypatch):
    monkeypatch.setattr(llm.settings, "llm_provider", "phoeniqs")
    monkeypatch.setattr(llm.settings, "phoeniqs_budget_tokens", 1000)
    monkeypatch.setattr(llm, "redis_client", _fake_redis(get_value="400"))
    s = await budget_status()
    assert s["metered"] is True
    assert s["spent"] == 400
    assert s["remaining"] == 600
    assert s["exhausted"] is False


# ---------------------------------------------------------------------------
# Piece 2 — price-watch move detection
# ---------------------------------------------------------------------------


def _position(**kw):
    base = dict(
        valor="123", mic="XNAS", isin="US1", issuer="ACME",
        security="ACME Rg", sub_asset_class="Equity",
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _price_session(added):
    s = MagicMock()
    s.add = MagicMock(side_effect=lambda o: added.append(o))
    return s


@pytest.mark.asyncio
async def test_price_move_emits_critical_above_threshold(monkeypatch):
    monkeypatch.setattr(pw.settings, "price_move_threshold_pct", 5.0)
    monkeypatch.setattr(pw.settings, "price_move_critical_pct", 10.0)
    # No cached baseline → falls back to session open (100) → close 110 = +10%.
    monkeypatch.setattr(pw, "cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(pw, "cache_set", AsyncMock())
    monkeypatch.setattr(pw, "should_suppress", AsyncMock(return_value=False))
    snap = SimpleNamespace(close=110.0, open=100.0, currency="USD", timestamp="2026-06-20")
    monkeypatch.setattr(pw.six, "get_eod_snapshot", AsyncMock(return_value=snap))

    added: list = []
    client = SimpleNamespace(id=uuid.uuid4(), name="Alice")
    made, ok = await _check_price_move(_price_session(added), client, _position(), [])

    assert (made, ok) == (1, True)
    assert len(added) == 1
    assert added[0].alert_class == "price_move"
    assert added[0].severity == pw.Severity.CRITICAL
    assert added[0].evidence[0]["isin"] == "US1"


@pytest.mark.asyncio
async def test_price_move_silent_below_threshold(monkeypatch):
    monkeypatch.setattr(pw.settings, "price_move_threshold_pct", 5.0)
    monkeypatch.setattr(pw.settings, "price_move_critical_pct", 10.0)
    monkeypatch.setattr(pw, "cache_get", AsyncMock(return_value=None))
    monkeypatch.setattr(pw, "cache_set", AsyncMock())
    monkeypatch.setattr(pw, "should_suppress", AsyncMock(return_value=False))
    snap = SimpleNamespace(close=102.0, open=100.0, currency="USD", timestamp="2026-06-20")
    monkeypatch.setattr(pw.six, "get_eod_snapshot", AsyncMock(return_value=snap))

    added: list = []
    client = SimpleNamespace(id=uuid.uuid4(), name="Alice")
    made, ok = await _check_price_move(_price_session(added), client, _position(), [])

    assert (made, ok) == (0, True)
    assert added == []


@pytest.mark.asyncio
async def test_price_move_skips_on_six_failure(monkeypatch):
    # No-fallbacks: a SIX error logs + skips, never invents a price.
    monkeypatch.setattr(pw.six, "get_eod_snapshot", AsyncMock(side_effect=ValueError("no close")))
    added: list = []
    client = SimpleNamespace(id=uuid.uuid4(), name="Alice")
    made, ok = await _check_price_move(_price_session(added), client, _position(), [])
    assert (made, ok) == (0, False)
    assert added == []


# ---------------------------------------------------------------------------
# Piece 3 — dispatch quiet hours + dedup
# ---------------------------------------------------------------------------


def test_is_quiet_hour_wraps_midnight():
    assert is_quiet_hour(23, 22, 7) is True
    assert is_quiet_hour(3, 22, 7) is True
    assert is_quiet_hour(7, 22, 7) is False   # end is exclusive
    assert is_quiet_hour(12, 22, 7) is False


def test_is_quiet_hour_same_bounds_means_none():
    assert is_quiet_hour(0, 0, 0) is False
    assert is_quiet_hour(13, 9, 9) is False


def _event(**kw):
    base = dict(
        id=uuid.uuid4(), entity_key="isin:US1", action="Price move",
        entity_label="ACME", source="price", magnitude=1.0, impact_score=900_000.0,
        client_count=2, total_exposure_chf=300_000.0, impacted_clients=[],
    )
    base.update(kw)
    return SimpleNamespace(**base)


def _dispatch_session(resolved, last_deliveries, added):
    """execute() returns the resolved list first, then one _last_delivery per call."""
    seq = []
    r0 = MagicMock()
    r0.scalars.return_value.all.return_value = resolved
    seq.append(r0)
    for d in last_deliveries:
        rd_ = MagicMock()
        rd_.scalars.return_value.first.return_value = d
        seq.append(rd_)
    s = MagicMock()
    s.execute = AsyncMock(side_effect=seq)
    s.add = MagicMock(side_effect=lambda o: added.append(o))
    s.commit = AsyncMock()
    return s


_DAYTIME = datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc)
_NIGHT = datetime(2026, 6, 20, 23, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_dispatch_pushes_critical_and_emails(monkeypatch):
    monkeypatch.setattr(rd.settings, "radar_critical_magnitude", 0.9)
    monkeypatch.setattr(rd.settings, "radar_quiet_start", 22)
    monkeypatch.setattr(rd.settings, "radar_quiet_end", 7)
    monkeypatch.setattr(rd.settings, "radar_digest_hour", 23)  # no digest at noon
    pub = MagicMock(return_value=1)
    monkeypatch.setattr(rd.radar_stream, "publish", pub)
    monkeypatch.setattr(rd.notify, "send_rm_email", AsyncMock(return_value=True))

    added: list = []
    session = _dispatch_session([_event()], [None], added)  # no prior delivery
    counts = await run_dispatch_cycle(session, _DAYTIME)

    assert counts["critical_pushed"] == 1
    assert counts["emails_sent"] == 1
    pub.assert_called_once()
    assert added and added[0].channel == "email"


@pytest.mark.asyncio
async def test_dispatch_dedups_already_delivered(monkeypatch):
    monkeypatch.setattr(rd.settings, "radar_critical_magnitude", 0.9)
    monkeypatch.setattr(rd.settings, "radar_rebroadcast_margin", 0.5)
    monkeypatch.setattr(rd.settings, "radar_digest_hour", 23)
    monkeypatch.setattr(rd.radar_stream, "publish", MagicMock(return_value=1))
    monkeypatch.setattr(rd.notify, "send_rm_email", AsyncMock(return_value=True))

    # Already delivered at the same impact → impact hasn't climbed past margin → skip.
    prior = SimpleNamespace(impact_at_delivery=900_000.0)
    added: list = []
    session = _dispatch_session([_event()], [prior], added)
    counts = await run_dispatch_cycle(session, _DAYTIME)

    assert counts["critical_pushed"] == 0
    assert added == []


@pytest.mark.asyncio
async def test_dispatch_quiet_hours_defers_email(monkeypatch):
    monkeypatch.setattr(rd.settings, "radar_critical_magnitude", 0.9)
    monkeypatch.setattr(rd.settings, "radar_quiet_start", 22)
    monkeypatch.setattr(rd.settings, "radar_quiet_end", 7)
    monkeypatch.setattr(rd.settings, "radar_digest_hour", 23)
    pub = MagicMock(return_value=1)
    monkeypatch.setattr(rd.radar_stream, "publish", pub)
    send = AsyncMock(return_value=True)
    monkeypatch.setattr(rd.notify, "send_rm_email", send)

    added: list = []
    session = _dispatch_session([_event()], [None], added)
    counts = await run_dispatch_cycle(session, _NIGHT)  # 23:00 → quiet

    assert counts["critical_pushed"] == 1   # SSE still fired
    assert counts["emails_sent"] == 0       # email deferred
    pub.assert_called_once()
    send.assert_not_awaited()
    assert added and added[0].channel == "sse"
