"""Unit tests for the precision matcher in app/loaders/news_match.py (EPIC-06).

Covers the false-positive fixes: whole-word matching (no substring), the
two-signal gate for common-word issuer names, ticker/ISIN signals, and the
entity-grounding field on the impact schema. All pure — no I/O, no mocking.
"""

from types import SimpleNamespace

import pytest

from app.loaders.news_match import (
    _ImpactResult,
    _entity_signals,
    _match_article,
    _whole_word,
    significant_name_tokens,
)
from app.news import NewsArticle


def _article(title: str = "", body: str = "", sentiment: float | None = None) -> NewsArticle:
    return NewsArticle(
        uri="u-1",
        title=title,
        body=body,
        url="https://example.com/a",
        source="Reuters",
        published_at="2026-06-20T10:00:00Z",
        sentiment=sentiment,
    )


def _watchlist(entities: list[dict] | None = None, themes: list[str] | None = None):
    return SimpleNamespace(entities=entities or [], themes=themes or [])


# ---------------------------------------------------------------------------
# _whole_word
# ---------------------------------------------------------------------------


def test_generic_sovereign_and_etf_names_yield_no_tokens():
    # Government bonds / ETFs have descriptive names whose tokens match news
    # incidentally — they must produce NO distinctive token (matched by ISIN/ticker).
    assert significant_name_tokens("United Mexican States") == []
    assert significant_name_tokens("iShares Listed Private Eq") == []
    assert significant_name_tokens("Bank of America Corp.") == []
    assert significant_name_tokens("Emerging Markets Equity Fund") == []
    # Distinctive equity brands still produce their identifying token.
    assert significant_name_tokens("Compagnie Financière Richemont SA") == ["richemont"]
    assert significant_name_tokens("Nestlé S.A.") == ["nestle"]


def test_incidental_geography_token_does_not_match_holding():
    # The real false positive: a Naira FX article mentioning "Mexican" must NOT
    # match the "United Mexican States" sovereign bond.
    wl = _watchlist(entities=[{"issuer": "United Mexican States", "ticker": "", "isin": "MX0001"}])
    art = _article(body="Naira depreciates as the Mexican peso also slid at the FX market", sentiment=0.0)
    mh, _ = _match_article(art, wl)
    assert mh == []


def test_whole_word_no_substring_match():
    assert _whole_word("intel", "intel posts record quarter") is True
    assert _whole_word("intel", "new intelligence report") is False
    assert _whole_word("abb", "the abbey opened") is False


# ---------------------------------------------------------------------------
# _entity_signals — (matched, strong)
# ---------------------------------------------------------------------------


def test_entity_signals_distinctive_name_in_headline_is_strong():
    e = {"issuer": "Compagnie Financière Richemont SA", "ticker": "CFR.SW", "isin": "CH0210483332"}
    matched, strong = _entity_signals(e, "richemont reports record sales", "")
    assert matched and strong


def test_entity_signals_distinctive_name_in_body_only_is_weak():
    # An incidental name-drop in the body (not the headline) is matched but weak.
    e = {"issuer": "Nestlé S.A.", "ticker": "NESN.SW", "isin": "CH0038863350"}
    matched, strong = _entity_signals(e, "grocery prices climb in europe", "analysts cited nestle among peers")
    assert matched is True
    assert strong is False


def test_entity_signals_common_word_is_weak():
    e = {"issuer": "Apple Inc.", "ticker": "AAPL", "isin": "US0378331005"}
    # "apple" the word matches, but it is ambiguous → matched but not strong
    matched, strong = _entity_signals(e, "i picked an apple from the tree", "")
    assert matched is True
    assert strong is False


def test_entity_signals_ticker_and_isin_are_strong():
    e = {"issuer": "Nestlé S.A.", "ticker": "NESN.SW", "isin": "CH0038863350"}
    assert _entity_signals(e, "nesn upgraded by analysts", "")[1] is True   # ticker base
    assert _entity_signals(e, "", "filing references ch0038863350 today")[1] is True  # ISIN anywhere


# ---------------------------------------------------------------------------
# _match_article — whole-word + two-signal gate
# ---------------------------------------------------------------------------


def test_match_article_whole_word_only():
    wl = _watchlist(entities=[{"issuer": "Intel Corp.", "ticker": "INTC", "isin": "US4581401001"}])
    # substring-only "intelligence" must NOT match
    mh, _ = _match_article(_article(title="New intelligence report released"), wl)
    assert mh == []
    # genuine whole-word mention matches (distinctive token → single signal is enough)
    mh, _ = _match_article(_article(title="Intel posts record quarter"), wl)
    assert len(mh) == 1 and mh[0]["issuer"] == "Intel Corp."


def test_match_article_body_only_mention_needs_corroboration():
    wl = _watchlist(entities=[{"issuer": "Nestlé S.A.", "ticker": "NESN.SW", "isin": "CH0038863350"}])
    # neutral article that merely name-drops Nestlé in the body → dropped
    mh, _ = _match_article(
        _article(title="Grocery prices rise across Europe", body="analysts cited nestle among others", sentiment=0.0),
        wl,
    )
    assert mh == []
    # Nestlé in the headline → kept (real subject)
    mh, _ = _match_article(_article(title="Nestlé lifts full-year guidance", body=""), wl)
    assert len(mh) == 1


def test_match_article_ambiguous_name_needs_corroboration():
    wl = _watchlist(entities=[{"issuer": "Apple Inc.", "ticker": "AAPL", "isin": "US0378331005"}])
    # bare ambiguous hit, no sentiment, no theme → dropped
    mh, _ = _match_article(_article(body="she ate an apple at lunch", sentiment=0.0), wl)
    assert mh == []
    # same hit corroborated by material sentiment → kept
    mh, _ = _match_article(_article(body="Apple shares surge on results", sentiment=0.6), wl)
    assert len(mh) == 1


def test_match_article_ambiguous_corroborated_by_theme():
    wl = _watchlist(
        entities=[{"issuer": "Apple Inc.", "ticker": "AAPL", "isin": "US0378331005"}],
        themes=["sustainability"],
    )
    art = _article(body="Apple touts a sustainability milestone", sentiment=0.0)
    mh, mt = _match_article(art, wl)
    assert len(mh) == 1
    assert mt and mt[0]["tag"] == "sustainability"


def test_match_article_theme_whole_word():
    wl = _watchlist(themes=["sustainability"])
    _, mt = _match_article(_article(body="a sustainability milestone was reached"), wl)
    assert mt and mt[0]["tag"] == "sustainability"
    # no spurious partial-word theme hit
    _, mt = _match_article(_article(body="completely unrelated content"), wl)
    assert mt == []


def test_match_article_isin_dedup_collapses_same_company():
    wl = _watchlist(
        entities=[
            {"issuer": "Nestlé S.A.", "ticker": "NESN.SW", "isin": "CH0038863350"},
            {"issuer": "Nestlé S.A.", "ticker": "NESN.SW", "isin": "CH0038863350"},
        ]
    )
    mh, _ = _match_article(_article(title="Nestlé lifts guidance"), wl)
    assert len(mh) == 1  # collapsed by ISIN


# ---------------------------------------------------------------------------
# _ImpactResult — entity-grounding field
# ---------------------------------------------------------------------------


def test_impact_result_about_holding_defaults_true():
    r = _ImpactResult(impact="threat", reason="x", confidence=0.5)
    assert r.about_holding is True


def test_impact_result_about_holding_can_be_false():
    r = _ImpactResult(about_holding=False, impact="moment", reason="wrong entity", confidence=0.1)
    assert r.about_holding is False
