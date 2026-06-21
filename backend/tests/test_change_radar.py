"""Unit tests for backend/app/loaders/change_radar.py (TASK-059, EPIC-08).

Pure helpers (entity extraction, magnitude, recency, scoring) need no mocking.
The orchestrator (build_change_radar) is exercised with a MagicMock session whose
execute() returns a scripted sequence — mirrors tests/test_alert_noise.py.
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.loaders.change_radar import (
    build_change_radar,
    dna_relevance,
    extract_alert_entity,
    recency_decay,
    score_event,
    signal_magnitude,
)

_NOW = datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# extract_alert_entity — pure
# ---------------------------------------------------------------------------


def _alert(alert_class, evidence, client_id=None):
    return SimpleNamespace(
        alert_class=alert_class,
        evidence=evidence,
        client_id=client_id or uuid.uuid4(),
    )


def test_extract_entity_drift_breach_is_sector():
    a = _alert("drift_breach", [{"sub_asset_class": "Equity DM", "drift_pp": 3.4}])
    etype, key, label, hint = extract_alert_entity(a)
    assert etype == "sector"
    assert key == "sac:Equity DM"
    assert label == "Equity DM"
    assert hint == "Equity DM"


def test_extract_entity_stale_sell_is_instrument():
    a = _alert("stale_sell", [{"isin": "CH001", "issuer": "ACME"}])
    etype, key, label, hint = extract_alert_entity(a)
    assert etype == "instrument"
    assert key == "isin:CH001"
    assert label == "ACME"
    assert hint == "CH001"


def test_extract_entity_dna_conflict_is_instrument():
    a = _alert("dna_conflict", [{"isin": "CH002", "security": "Sec X"}])
    etype, key, label, _ = extract_alert_entity(a)
    assert etype == "instrument"
    assert key == "isin:CH002"
    assert label == "Sec X"


def test_extract_entity_guardrail_uses_candidate_isin():
    a = _alert("behavioural_guardrail", [{"candidate_isin": "CH003"}])
    etype, key, _, hint = extract_alert_entity(a)
    assert etype == "instrument"
    assert key == "isin:CH003"
    assert hint == "CH003"


@pytest.mark.parametrize("cls", ["values_drift", "quiet_client", "overdue_promise"])
def test_extract_entity_relationship_classes_are_client(cls):
    cid = uuid.uuid4()
    a = _alert(cls, [{}], client_id=cid)
    etype, key, label, hint = extract_alert_entity(a)
    assert etype == "client"
    assert key == f"client:{cid}"
    assert hint is None


def test_extract_entity_missing_field_returns_none():
    # drift with no sub_asset_class, stale_sell with no isin → unresolvable
    assert extract_alert_entity(_alert("drift_breach", [{}])) is None
    assert extract_alert_entity(_alert("stale_sell", [{}])) is None
    assert extract_alert_entity(_alert("unknown_class", [{}])) is None


def test_two_same_isin_alerts_group_to_one_entity_key():
    """Fan-out inversion: two clients' alerts on the same instrument share an entity_key."""
    a1 = extract_alert_entity(_alert("stale_sell", [{"isin": "CH9", "issuer": "X"}]))
    a2 = extract_alert_entity(_alert("dna_conflict", [{"isin": "CH9", "issuer": "X"}]))
    assert a1[1] == a2[1] == "isin:CH9"


# ---------------------------------------------------------------------------
# magnitude / dna_relevance / recency / score — pure
# ---------------------------------------------------------------------------


def test_signal_magnitude_scales_with_severity_and_confidence():
    assert signal_magnitude("Critical", 1.0) == pytest.approx(1.0)
    assert signal_magnitude("Attention", 1.0) == pytest.approx(0.6)
    assert signal_magnitude("FYI", 1.0) == pytest.approx(0.3)
    # confidence scales it down; unknown severity floors at 0.3 base
    assert signal_magnitude("Critical", 0.5) == pytest.approx(0.5)
    assert signal_magnitude(None, None) == pytest.approx(0.3 * 0.7)


def test_dna_relevance_lifts_dna_rooted_classes():
    assert dna_relevance("dna_conflict") == 1.5
    assert dna_relevance("behavioural_guardrail") == 1.5
    assert dna_relevance("panic") == 1.5
    assert dna_relevance("drift_breach") == 1.0
    assert dna_relevance(None) == 1.0


def test_recency_decay_halves_each_half_life():
    fresh = recency_decay(_NOW, _NOW, half_life_days=14)
    half = recency_decay(_NOW - timedelta(days=14), _NOW, half_life_days=14)
    quarter = recency_decay(_NOW - timedelta(days=28), _NOW, half_life_days=14)
    assert fresh == pytest.approx(1.0)
    assert half == pytest.approx(0.5)
    assert quarter == pytest.approx(0.25)
    assert recency_decay(None, _NOW) == pytest.approx(0.5)


def test_score_event_sums_contributions_times_recency():
    # two clients: exposure × magnitude × dna_relevance, then × recency(1.0 fresh)
    contribs = [(100_000.0, 1.0, 1.0), (50_000.0, 0.6, 1.5)]
    expected_base = 100_000.0 * 1.0 * 1.0 + 50_000.0 * 0.6 * 1.5
    assert score_event(contribs, _NOW, _NOW) == pytest.approx(expected_base)


def test_score_event_recency_lowers_old_events():
    contribs = [(100_000.0, 1.0, 1.0)]
    fresh = score_event(contribs, _NOW, _NOW)
    old = score_event(contribs, _NOW - timedelta(days=14), _NOW)
    assert old == pytest.approx(fresh * 0.5)


def test_score_event_empty_is_zero():
    assert score_event([], _NOW, _NOW) == 0.0


# ---------------------------------------------------------------------------
# build_change_radar — orchestrator with scripted MagicMock session
# ---------------------------------------------------------------------------


def _scalars_result(items):
    r = MagicMock()
    r.scalars.return_value.all.return_value = items
    return r


def _all_result(items):
    r = MagicMock()
    r.all.return_value = items
    return r


def _make_session(execute_results, added):
    session = MagicMock()
    session.execute = AsyncMock(side_effect=execute_results)
    session.add = MagicMock(side_effect=lambda obj: added.append(obj))
    session.commit = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_fanout_one_instrument_two_clients_single_event():
    """One CIO SELL instrument held by two clients → one event, client_count=2."""
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    clients = [SimpleNamespace(id=c1, name="Alice"), SimpleNamespace(id=c2, name="Bob")]
    positions = [
        SimpleNamespace(client_id=c1, isin="CH9", sub_asset_class="Eq", current_chf=200_000.0),
        SimpleNamespace(client_id=c2, isin="CH9", sub_asset_class="Eq", current_chf=100_000.0),
    ]
    alerts = [
        SimpleNamespace(
            id=uuid.uuid4(), client_id=c1, alert_class="stale_sell", severity="Critical",
            confidence=1.0, created_at=_NOW, status="open", trigger="ACME SELL",
            why="held SELL", suggested_action="dispose",
            evidence=[{"isin": "CH9", "issuer": "ACME", "current_chf": 200_000.0}],
        ),
        SimpleNamespace(
            id=uuid.uuid4(), client_id=c2, alert_class="stale_sell", severity="Attention",
            confidence=1.0, created_at=_NOW, status="open", trigger="ACME SELL",
            why="held SELL", suggested_action="dispose",
            evidence=[{"isin": "CH9", "issuer": "ACME", "current_chf": 100_000.0}],
        ),
    ]
    added: list = []
    session = _make_session(
        [
            MagicMock(),                 # delete(ChangeEvent)
            _scalars_result(clients),    # select(Client)
            _scalars_result(positions),  # select(Position)
            _all_result([]),             # select(SwapProposal join) — no swaps
            _scalars_result(alerts),     # select(Alert)
            _scalars_result([]),         # select(NewsItem)
        ],
        added,
    )

    result = await build_change_radar(session)

    assert result["events_written"] == 1
    assert result["unresolved"] == 0
    event = added[0]
    assert event.entity_key == "isin:CH9"
    assert event.entity_type == "instrument"
    assert event.client_count == 2
    assert float(event.total_exposure_chf) == pytest.approx(300_000.0)
    assert event.suggested_batch_action is not None
    assert event.unresolved_reason is None
    # impacted clients ranked by exposure desc
    assert event.impacted_clients[0]["client_name"] == "Alice"
    assert event.impacted_clients[0]["exposure_chf"] == pytest.approx(200_000.0)


@pytest.mark.asyncio
async def test_instrument_event_attaches_swap_candidate():
    """A dna_conflict on a held instrument attaches that holder's best swap (one-click fix)."""
    c1 = uuid.uuid4()
    clients = [SimpleNamespace(id=c1, name="Alice")]
    positions = [SimpleNamespace(client_id=c1, isin="CH9", sub_asset_class="Eq", current_chf=80_000.0)]
    swap_join = [
        (
            SimpleNamespace(
                candidate_isin="CHX", candidate_valor="V1", fit_gain=0.4, dna_reason="resolves exclusion"
            ),
            SimpleNamespace(client_id=c1, isin="CH9"),
        )
    ]
    alerts = [
        SimpleNamespace(
            id=uuid.uuid4(), client_id=c1, alert_class="dna_conflict", severity="Critical",
            confidence=1.0, created_at=_NOW, status="open", trigger="conflict",
            why="violates exclusion", suggested_action="swap",
            evidence=[{"isin": "CH9", "issuer": "ACME"}],
        ),
    ]
    added: list = []
    session = _make_session(
        [
            MagicMock(),
            _scalars_result(clients),
            _scalars_result(positions),
            _all_result(swap_join),
            _scalars_result(alerts),
            _scalars_result([]),
        ],
        added,
    )

    await build_change_radar(session)

    event = added[0]
    assert event.entity_key == "isin:CH9"
    swap = event.impacted_clients[0]["swap_candidate"]
    assert swap is not None
    assert swap["candidate_isin"] == "CHX"
    assert swap["fit_gain"] == pytest.approx(0.4)


@pytest.mark.asyncio
async def test_unresolvable_alert_is_surfaced_not_dropped():
    """An alert with no extractable entity becomes an unresolved row (no-fallbacks)."""
    c1 = uuid.uuid4()
    clients = [SimpleNamespace(id=c1, name="Alice")]
    positions = [SimpleNamespace(client_id=c1, isin="CH9", sub_asset_class="Eq", current_chf=100_000.0)]
    alerts = [
        SimpleNamespace(
            id=uuid.uuid4(), client_id=c1, alert_class="drift_breach", severity="Attention",
            confidence=1.0, created_at=_NOW, status="open", trigger="bad drift",
            why="w", suggested_action="s",
            evidence=[{}],  # no sub_asset_class → unresolvable
        ),
    ]
    added: list = []
    session = _make_session(
        [
            MagicMock(),
            _scalars_result(clients),
            _scalars_result(positions),
            _all_result([]),
            _scalars_result(alerts),
            _scalars_result([]),
        ],
        added,
    )

    result = await build_change_radar(session)

    assert result["unresolved"] == 1
    assert len(added) == 1
    row = added[0]
    assert row.client_count == 0
    assert row.unresolved_reason is not None
    assert row.entity_key is None
