"""Unit tests for backend/app/loaders/message_render.py (TASK-038).

Tests are network-free: _guardrail and _build_provenance are pure functions;
render_message_draft is tested by patching chat() so no LLM or DB is needed.
"""
import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.loaders.message_render import _build_provenance, _guardrail


# ---------------------------------------------------------------------------
# _guardrail — pure function, no mocking needed
# ---------------------------------------------------------------------------

_FACT_SHEET = {
    "trigger": "DNA conflict on Nestlé AG",
    "holding": {"issuer": "Nestlé AG", "current_chf": 125000.0},
    "numbers": {"current_chf": 125000.0, "portfolio_pct": 8.33},
    "proposal": {"fit_gain": 0.15},
    "mandate_impact_unchanged": True,
    "dna_points": [],
    "evidence": [],
}


def test_guardrail_passes_when_numbers_match():
    draft = "Your Nestlé AG holding is currently valued at 125000.0 CHF, representing 8.33% of your portfolio."
    ok, hallucinated = _guardrail(draft, _FACT_SHEET)
    assert ok is True
    assert hallucinated == []


def test_guardrail_fails_on_hallucinated_number():
    draft = "Your Nestlé AG holding is valued at 999999 CHF."
    ok, hallucinated = _guardrail(draft, _FACT_SHEET)
    assert ok is False
    assert "999999" in hallucinated


def test_guardrail_fails_on_abbreviation():
    draft = "Your holding is currently valued at 1.25M CHF."
    ok, hallucinated = _guardrail(draft, _FACT_SHEET)
    assert ok is False
    # "1.25" and/or "1" and/or "25" may appear; the important thing is it fails
    assert hallucinated  # at least one hallucinated number detected


def test_guardrail_ignores_commas_in_number():
    # "125,000.0" should normalise to "125000.0" which is in the fact sheet
    fact = {"numbers": {"current_chf": 125000.0}}
    draft = "The position is worth 125,000.0 CHF."
    # "125000.0" is in json.dumps(fact); "125000.0" extracted from draft after comma-strip
    ok, hallucinated = _guardrail(draft, fact)
    assert ok is True


def test_guardrail_passes_empty_draft():
    ok, hallucinated = _guardrail("No numbers here.", _FACT_SHEET)
    assert ok is True
    assert hallucinated == []


# ---------------------------------------------------------------------------
# _build_provenance — pure function
# ---------------------------------------------------------------------------


def test_build_provenance_matches_issuer():
    fact = {"holding": {"issuer": "Nestlé AG"}}
    draft = "Your Nestlé AG position has drifted outside the mandate bands."
    entries = _build_provenance(draft, fact)
    keys = [e["fact_key"] for e in entries]
    assert "holding.issuer" in keys


def test_build_provenance_skips_short_values():
    fact = {"numbers": {"portfolio_pct": 8.33}, "status": "ok"}
    draft = "The allocation is 8.33 percent — ok for now."
    entries = _build_provenance(draft, fact)
    keys = [e["fact_key"] for e in entries]
    # "ok" has len 2, should be skipped
    assert "status" not in keys


def test_build_provenance_empty_when_no_match():
    fact = {"holding": {"issuer": "Nestlé AG"}}
    draft = "Your current allocation warrants attention."
    entries = _build_provenance(draft, fact)
    assert entries == []


# ---------------------------------------------------------------------------
# render_message_draft — patched chat() and DB session
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_render_message_draft_happy_path():
    from uuid import uuid4

    draft_id = uuid4()
    client_id = uuid4()

    fact_sheet = {
        "trigger": "DNA conflict",
        "holding": {"issuer": "Nestlé AG", "current_chf": 125000.0},
        "numbers": {"current_chf": 125000.0, "portfolio_pct": 8.33},
        "proposal": None,
        "mandate_impact_unchanged": True,
        "dna_points": [],
        "evidence": [],
    }

    mock_draft = MagicMock()
    mock_draft.id = draft_id
    mock_draft.client_id = client_id
    mock_draft.fact_sheet = fact_sheet

    mock_dna = MagicMock()
    mock_dna.style_profile = {
        "preset": "data-driven",
        "analytical_emotional": 0.8,
        "brief_detailed": 0.6,
        "formal_warm": 0.7,
        "data_values": 0.75,
        "risk_opportunity": 0.4,
        "language_formality": "formal",
        "signature_phrases": [],
    }

    mock_scalar = AsyncMock(side_effect=[mock_draft, mock_dna])
    mock_execute = AsyncMock()
    mock_commit = AsyncMock()

    session = MagicMock()
    session.scalar = mock_scalar
    session.execute = mock_execute
    session.commit = mock_commit

    llm_response = json.dumps({
        "draft": (
            "Dear valued client, your Nestlé AG position (125000.0 CHF, 8.33% of portfolio) "
            "warrants attention. We recommend discussing your options. Shall we discuss?"
        ),
        "facts_used": ["numbers.current_chf", "numbers.portfolio_pct"],
    })

    with patch("app.loaders.message_render.json_chat", new=AsyncMock(return_value=MagicMock(
        draft=(
            "Dear valued client, your Nestlé AG position (125000.0 CHF, 8.33% of portfolio) "
            "warrants attention. We recommend discussing your options. Shall we discuss?"
        ),
        facts_used=["numbers.current_chf", "numbers.portfolio_pct"],
    ))):
        from app.loaders.message_render import render_message_draft
        result = await render_message_draft(session, draft_id)

    assert result["guardrail_passed"] is True
    assert result["preset"] == "data-driven"
    assert "125000.0" in result["draft_text"]
    assert "numbers.current_chf" in result["facts_used"]
    mock_commit.assert_called_once()


@pytest.mark.asyncio
async def test_render_message_draft_guardrail_rejects():
    from uuid import uuid4

    draft_id = uuid4()
    client_id = uuid4()

    fact_sheet = {
        "numbers": {"current_chf": 125000.0},
        "holding": {"issuer": "Nestlé AG"},
        "proposal": None,
        "mandate_impact_unchanged": True,
        "dna_points": [],
        "evidence": [],
        "trigger": "test",
    }

    mock_draft = MagicMock()
    mock_draft.id = draft_id
    mock_draft.client_id = client_id
    mock_draft.fact_sheet = fact_sheet

    mock_dna = MagicMock()
    mock_dna.style_profile = None

    session = MagicMock()
    session.scalar = AsyncMock(side_effect=[mock_draft, mock_dna])
    session.execute = AsyncMock()
    session.commit = AsyncMock()

    with patch("app.loaders.message_render.json_chat", new=AsyncMock(return_value=MagicMock(
        draft="Your holding is worth 999999 CHF — a hallucinated number.",
        facts_used=[],
    ))):
        from app.loaders.message_render import render_message_draft
        with pytest.raises(RuntimeError, match="MSG4 guardrail"):
            await render_message_draft(session, draft_id)

    session.commit.assert_not_called()
