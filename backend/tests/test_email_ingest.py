"""Unit tests for backend/app/loaders/email_ingest.py (TASK-060, EPIC-08).

Pure helpers (similarity, magnitude, direction, thread-rep, resolvers) need no
mocking. Signal construction is driven with SimpleNamespace stand-ins for ORM rows
and a constructed classification. The headline test proves an email signal merges
with an Alert on the same instrument inside build_change_radar (cross-channel dedup).
"""

import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.graph_mail import GraphMessage
from app.loaders import email_ingest as ei
from app.loaders.change_radar import RadarSignal, build_change_radar
from app.loaders.email_ingest import (
    _EmailClassification,
    _EmailEntity,
    _is_outbound,
    _pick_thread_representative,
    _resolve_client,
    _resolve_instrument_isin,
    _signals_for_email,
    email_dna_relevance,
    email_magnitude,
    name_similarity,
)
from app.models.enums import Mandate

_NOW = datetime(2026, 6, 20, 12, 0, 0, tzinfo=timezone.utc)
_MAILBOX = "rm@bank.com"


def _msg(**kw) -> GraphMessage:
    base = dict(id="m1", conversation_id="c1", subject="Re: portfolio", received_at=_NOW)
    base.update(kw)
    return GraphMessage(**base)


# ---------------------------------------------------------------------------
# name_similarity — pure
# ---------------------------------------------------------------------------


def test_name_similarity_exact_and_local_part():
    assert name_similarity("Clara Bauer", "Clara Bauer") == pytest.approx(1.0)
    # local-part of an address normalises to the same tokens → full overlap
    assert name_similarity("Clara Bauer", "clara.bauer") == pytest.approx(1.0)
    # token order doesn't matter
    assert name_similarity("Bauer Clara", "Clara Bauer") == pytest.approx(1.0)


def test_name_similarity_unrelated_is_low():
    assert name_similarity("Clara Bauer", "Hubertus Schneider") < 0.4


def test_name_similarity_empty_is_zero():
    assert name_similarity(None, "x") == 0.0
    assert name_similarity("x", "") == 0.0


# ---------------------------------------------------------------------------
# email_magnitude / dna_relevance / direction — pure
# ---------------------------------------------------------------------------


def test_email_magnitude_bands_and_outbound_damping():
    assert email_magnitude("high", 1.0, outbound=False) == pytest.approx(1.0)
    assert email_magnitude("medium", 0.0, outbound=False) == pytest.approx(0.3)  # 0.6 * 0.5
    assert email_magnitude("low", 1.0, outbound=False) == pytest.approx(0.3)
    # unknown urgency floors at 0.3 base
    assert email_magnitude("???", 1.0, outbound=False) == pytest.approx(0.3)
    # outbound is context-only → damped to 0.3x
    assert email_magnitude("high", 1.0, outbound=True) == pytest.approx(0.3)


def test_email_dna_relevance_lifts_negative_client_email():
    assert email_dna_relevance("client", -0.8) == 1.5
    assert email_dna_relevance("client", 0.5) == 1.0
    assert email_dna_relevance("instrument", -0.8) == 1.0


def test_is_outbound_is_case_insensitive():
    assert _is_outbound(_msg(from_address="RM@Bank.com"), _MAILBOX) is True
    assert _is_outbound(_msg(from_address="clara@ex.com"), _MAILBOX) is False
    assert _is_outbound(_msg(from_address=None), _MAILBOX) is False


def test_pick_thread_representative_prefers_recent_inbound():
    old_in = _msg(id="a", from_address="clara@ex.com", received_at=_NOW - timedelta(days=2))
    new_in = _msg(id="b", from_address="clara@ex.com", received_at=_NOW)
    outbound = _msg(id="c", from_address=_MAILBOX, received_at=_NOW + timedelta(hours=1))
    rep = _pick_thread_representative([old_in, outbound, new_in], _MAILBOX)
    assert rep.id == "b"  # newest inbound, ignoring the even-newer outbound reply


def test_pick_thread_representative_all_outbound_keeps_latest():
    o1 = _msg(id="a", from_address=_MAILBOX, received_at=_NOW - timedelta(days=1))
    o2 = _msg(id="b", from_address=_MAILBOX, received_at=_NOW)
    rep = _pick_thread_representative([o1, o2], _MAILBOX)
    assert rep.id == "b"


# ---------------------------------------------------------------------------
# resolvers — pure
# ---------------------------------------------------------------------------


def _pos(client_id, isin, issuer="ACME Corp", security=None, current_chf=100_000.0):
    return SimpleNamespace(
        client_id=client_id, isin=isin, issuer=issuer, security=security, current_chf=current_chf
    )


def test_resolve_instrument_explicit_isin_wins():
    e = _EmailEntity(kind="instrument", name="Nestle", isin="CH0038863350")
    isin, label = _resolve_instrument_isin(e, [], [])
    assert isin == "CH0038863350"


def test_resolve_instrument_fuzzy_matches_held_issuer():
    positions = [_pos(uuid.uuid4(), "CH9", issuer="Nestle SA")]
    e = _EmailEntity(kind="instrument", name="Nestle")
    isin, label = _resolve_instrument_isin(e, positions, [])
    assert isin == "CH9"


def test_resolve_instrument_unheld_returns_none():
    positions = [_pos(uuid.uuid4(), "CH9", issuer="Nestle SA")]
    e = _EmailEntity(kind="instrument", name="Tesla")
    isin, _ = _resolve_instrument_isin(e, positions, [])
    assert isin is None


def test_resolve_client_matches_by_contact_then_unmatched_is_none():
    cid = uuid.uuid4()
    clients = [SimpleNamespace(id=cid, name="[SIMULATED] Clara Bauer", mandate=Mandate.BALANCED)]
    contacts = {str(cid): ["Clara Bauer"]}
    # display name fails against the bracketed client.name but matches client_contact
    assert _resolve_client("Clara Bauer", "clara.bauer@ex.com", clients, contacts).id == cid
    # nobody resembling this sender → None (bucketed by caller, never dropped)
    assert _resolve_client("Zzz Nobody", "zzz@ex.com", clients, contacts) is None


# ---------------------------------------------------------------------------
# _signals_for_email — async, no LLM/Graph
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_instrument_email_fans_out_one_signal_per_holder():
    c1, c2 = uuid.uuid4(), uuid.uuid4()
    positions = [_pos(c1, "CH9", current_chf=200_000.0), _pos(c2, "CH9", current_chf=100_000.0)]
    cls = _EmailClassification(
        action="Sell request",
        entities=[_EmailEntity(kind="instrument", name="ACME", isin="CH9")],
        urgency="high",
        sentiment=-0.2,
    )
    out = await _signals_for_email(_msg(from_address="desk@bank.com"), cls, _MAILBOX, [], positions, [], {})
    assert len(out) == 2
    assert {s.client_id for s in out} == {str(c1), str(c2)}
    assert all(s.entity_key == "isin:CH9" and s.source == "email" for s in out)
    assert all(s.entity_type == "instrument" for s in out)


@pytest.mark.asyncio
async def test_inbound_client_email_resolves_one_client():
    cid = uuid.uuid4()
    clients = [SimpleNamespace(id=cid, name="Clara Bauer", mandate=Mandate.BALANCED)]
    cls = _EmailClassification(
        action="Complaint",
        entities=[_EmailEntity(kind="client")],
        urgency="medium",
        sentiment=-0.7,
    )
    msg = _msg(from_name="Clara Bauer", from_address="clara.bauer@ex.com")
    out = await _signals_for_email(msg, cls, _MAILBOX, clients, [], [], {})
    assert len(out) == 1
    assert out[0].entity_key == f"client:{cid}"
    assert out[0].entity_type == "client"
    assert out[0].dna_relevance == 1.5  # negative-sentiment client email lifts relevance


@pytest.mark.asyncio
async def test_book_email_fans_out_by_mandate():
    g1, g2, b1 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    clients = [
        SimpleNamespace(id=g1, name="G One", mandate=Mandate.GROWTH),
        SimpleNamespace(id=g2, name="G Two", mandate=Mandate.GROWTH),
        SimpleNamespace(id=b1, name="B One", mandate=Mandate.BALANCED),
    ]
    cls = _EmailClassification(
        action="De-risk",
        entities=[_EmailEntity(kind="book", name="de-risk the Growth book")],
        urgency="high",
        sentiment=0.0,
    )
    out = await _signals_for_email(_msg(from_address="cio@bank.com"), cls, _MAILBOX, clients, [], [], {})
    assert len(out) == 2  # only the two Growth clients
    assert {s.client_id for s in out} == {str(g1), str(g2)}
    assert all(s.entity_type == "macro" and s.entity_key == "email:book:Growth" for s in out)


@pytest.mark.asyncio
async def test_fully_unresolved_email_is_bucketed_not_dropped():
    cls = _EmailClassification(
        action="Question",
        entities=[_EmailEntity(kind="client", name="Nobody Here")],
        urgency="low",
        sentiment=0.0,
    )
    msg = _msg(from_name="Nobody", from_address="nobody@ex.com")
    out = await _signals_for_email(msg, cls, _MAILBOX, [], [], [], {})
    assert len(out) == 1
    assert out[0].entity_key.startswith("email:unresolved:")
    assert out[0].client_id.startswith("unmatched:")


# ---------------------------------------------------------------------------
# _classify_email — mocks the LLM
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_classify_email_calls_json_chat(monkeypatch):
    fake = _EmailClassification(action="Sell request", entities=[], urgency="high", sentiment=-0.5)
    mock = AsyncMock(return_value=fake)
    monkeypatch.setattr(ei, "json_chat", mock)
    result = await ei._classify_email(_msg(subject="sell Nestle", body_text="please sell"))
    assert result.action == "Sell request"
    assert mock.await_count == 1


# ---------------------------------------------------------------------------
# config gate — disabled returns [] with no Graph/LLM call
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_ingest_disabled_returns_empty(monkeypatch):
    monkeypatch.setattr(ei.settings, "ms_graph_tenant_id", "")
    monkeypatch.setattr(ei.settings, "ms_graph_client_id", "")
    monkeypatch.setattr(ei.settings, "ms_graph_client_secret", "")
    monkeypatch.setattr(ei.settings, "ms_graph_mailbox", "")
    fetch = AsyncMock()
    monkeypatch.setattr(ei, "fetch_recent_messages", fetch)
    assert await ei.ingest_email_signals(MagicMock()) == []
    fetch.assert_not_awaited()


# ---------------------------------------------------------------------------
# cross-channel merge — the headline AC, through build_change_radar
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
async def test_email_signal_merges_with_alert_on_same_instrument():
    """An email signal on CH9 + a stale_sell alert on CH9 collapse to ONE event."""
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
            evidence=[{"isin": "CH9", "issuer": "ACME"}],
        ),
    ]
    # Email signal for the OTHER holder (c2), same instrument.
    email_sig = RadarSignal(
        entity_key="isin:CH9", entity_type="instrument", entity_label="ACME",
        action="Sell request", source="email", client_id=str(c2),
        magnitude=0.6, dna_relevance=1.0, event_ts=_NOW, isins=["CH9"],
        dna_note="Email: sell ACME", suggested_action="Sell request",
    )
    added: list = []
    session = _make_session(
        [
            MagicMock(),                 # delete(ChangeEvent)
            _scalars_result(clients),    # select(Client)
            _scalars_result(positions),  # select(Position)
            _all_result([]),             # select(SwapProposal join)
            _scalars_result(alerts),     # select(Alert)
            _scalars_result([]),         # select(NewsItem)
        ],
        added,
    )

    result = await build_change_radar(session, extra_signals=[email_sig])

    assert result["events_written"] == 1  # one merged event, not two
    event = added[0]
    assert event.entity_key == "isin:CH9"
    assert event.client_count == 2  # alert (c1) + email (c2) on the same instrument
    assert float(event.total_exposure_chf) == pytest.approx(300_000.0)
