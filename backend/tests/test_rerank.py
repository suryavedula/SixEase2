"""Unit tests for the cross-encoder rerank gate (app/loaders/rerank.py, EPIC-06 C2).

The actual ONNX model is never loaded here: the disabled path must not import
fastembed at all, and the enabled path is exercised by monkeypatching the sync
scorer. So these run with or without the optional dependency installed.
"""

import pytest

import app.loaders.rerank as rerank


# ---------------------------------------------------------------------------
# build_query — pure
# ---------------------------------------------------------------------------


def test_build_query_from_holdings_and_themes():
    q = rerank.build_query(
        [{"issuer": "Intel Corp."}, {"issuer": "Nestlé S.A."}],
        [{"tag": "sustainability"}],
    )
    assert q == "news about Intel Corp., Nestlé S.A., sustainability"


def test_build_query_empty_falls_back_to_generic():
    assert rerank.build_query([], []) == "relevant financial news"


# ---------------------------------------------------------------------------
# passes_cross_encoder — gate off / on
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_gate_disabled_is_noop_and_does_not_load_model(monkeypatch):
    monkeypatch.setattr(rerank.settings, "news_cross_encoder_enabled", False)
    # If the gate tried to score, this would blow up — proving it short-circuits.
    monkeypatch.setattr(
        rerank, "_score_sync",
        lambda *a, **k: pytest.fail("scorer must not run when gate is disabled"),
    )
    passed, score = await rerank.passes_cross_encoder("any text", [{"issuer": "X"}], [])
    assert passed is True
    assert score is None


@pytest.mark.asyncio
async def test_gate_enabled_keeps_high_score(monkeypatch):
    monkeypatch.setattr(rerank.settings, "news_cross_encoder_enabled", True)
    monkeypatch.setattr(rerank.settings, "news_cross_encoder_min_score", 0.0)
    monkeypatch.setattr(rerank, "_score_sync", lambda q, d: 4.2)
    passed, score = await rerank.passes_cross_encoder("on-topic", [], [{"tag": "esg"}])
    assert passed is True
    assert score == pytest.approx(4.2)


@pytest.mark.asyncio
async def test_gate_enabled_drops_low_score(monkeypatch):
    monkeypatch.setattr(rerank.settings, "news_cross_encoder_enabled", True)
    monkeypatch.setattr(rerank.settings, "news_cross_encoder_min_score", 0.0)
    monkeypatch.setattr(rerank, "_score_sync", lambda q, d: -3.7)
    passed, score = await rerank.passes_cross_encoder("off-topic", [], [{"tag": "esg"}])
    assert passed is False
    assert score == pytest.approx(-3.7)
