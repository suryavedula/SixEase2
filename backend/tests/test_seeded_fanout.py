"""Unit tests for the seeded-news fan-out + global-index cap (TASK-061 fix).

Pure helpers (significant_name_tokens, issuer_in_headline) need no I/O. The async
fan-out and global index are driven with scripted MagicMock sessions, mirroring
tests/test_change_radar.py.
"""

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.loaders.news_match import (
    fanout_seeded_news,
    issuer_in_headline,
    significant_name_tokens,
)
from app.loaders.watchlist import get_global_index


# ---------------------------------------------------------------------------
# significant_name_tokens / issuer_in_headline — pure
# ---------------------------------------------------------------------------


def test_significant_tokens_drops_generic_words():
    assert significant_name_tokens("Intel Corp.") == ["intel"]
    assert significant_name_tokens("Compagnie Financière Richemont SA") == ["richemont"]
    # purely generic names have no distinctive token
    assert significant_name_tokens("Swiss Bank") == []
    assert significant_name_tokens("US Treasury") == []
    assert significant_name_tokens("ZKB Bond") == []


def test_issuer_in_headline_matches_short_name_in_legal_name():
    hl = "lvmh and richemont report record q2 sales as luxury rebounds".lower()
    assert issuer_in_headline("LVMH Moët Hennessy", hl) is True
    assert issuer_in_headline("Compagnie Financière Richemont SA", hl) is True
    # a bond instrument must NOT match a headline that merely says "bonds"
    assert issuer_in_headline("ZKB Bond", "eu sustainable finance — green bonds pass") is False


def test_issuer_in_headline_whole_word_only():
    # "intel" should not match inside "intelligence"
    assert issuer_in_headline("Intel Corp.", "new intelligence report released") is False
    assert issuer_in_headline("Intel Corp.", "intel posts record quarter") is True


# ---------------------------------------------------------------------------
# fanout_seeded_news — async, scripted session
# ---------------------------------------------------------------------------


def _scalars(items):
    r = MagicMock()
    r.scalars.return_value.all.return_value = items  # not used; we use session.scalars
    return r


def _make_session(scalars_side_effect):
    session = MagicMock()

    async def scalars(_query):
        res = MagicMock()
        res.all.return_value = scalars_side_effect.pop(0)
        return res

    session.scalars = AsyncMock(side_effect=scalars)
    session.commit = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_fanout_sets_all_holders_and_clears_unmatched():
    c1, c2, c3 = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    # Two seeded items: one names a held instrument, one names nothing held.
    lvmh = SimpleNamespace(
        headline="LVMH and Richemont report record sales",
        is_seeded=True,
        client_ids=["stale"],          # stale from a prior run
        matched_holdings=[{"x": 1}],
    )
    esg = SimpleNamespace(
        headline="EU sustainable finance package passes",
        is_seeded=True,
        client_ids=["stale2"],         # must be cleared
        matched_holdings=[{"y": 2}],
    )
    positions = [
        SimpleNamespace(client_id=c1, isin="FR1", issuer="LVMH Moët Hennessy", valor="v1"),
        SimpleNamespace(client_id=c2, isin="FR1", issuer="LVMH Moët Hennessy", valor="v1"),
        SimpleNamespace(client_id=c3, isin="CH9", issuer="Nestlé S.A.", valor="v2"),
    ]
    session = _make_session([[lvmh, esg], positions])

    result = await fanout_seeded_news(session)

    assert result == {"seeded_articles": 2, "fanned_out": 1, "unmatched": 1}
    # LVMH fanned out to both holders of FR1
    assert sorted(lvmh.client_ids) == sorted([str(c1), str(c2)])
    assert lvmh.matched_holdings[0]["isin"] == "FR1"
    # unmatched article had its stale fan-out cleared (idempotent)
    assert esg.client_ids == []
    assert esg.matched_holdings == []


# ---------------------------------------------------------------------------
# get_global_index — cap + generic-name drop + breadth ranking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_index_caps_drops_generic_and_ranks_by_breadth(monkeypatch):
    import app.loaders.watchlist as wl

    monkeypatch.setattr(wl.settings, "news_max_keywords", 2)
    # "Nestlé" held by 2 clients (breadth 2), "ASML" by 1; "Swiss Bank" is generic.
    rows = [
        SimpleNamespace(
            entities=[{"issuer": "Nestlé S.A."}, {"issuer": "Swiss Bank"}],
            themes=["esg"],
        ),
        SimpleNamespace(
            entities=[{"issuer": "Nestlé S.A."}, {"issuer": "ASML Holding N.V."}],
            themes=[],
        ),
    ]
    session = MagicMock()
    res = MagicMock()
    res.scalars.return_value.all.return_value = rows
    session.execute = AsyncMock(return_value=res)

    idx = await get_global_index(session)

    assert idx["keyword_count"] == 2  # capped
    # Nestlé (breadth 2) ranks first; "Swiss Bank" dropped as generic
    assert idx["keywords"][0] == "Nestlé S.A."
    assert "Swiss Bank" not in idx["keywords"]
