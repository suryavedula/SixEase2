"""Tests for domain agent wrappers (TASK-054 / EPIC-13).

Each agent is tested for:
- happy path: engine returns successfully → AgentResult.status == "ok"
- error path:  engine raises RuntimeError → AgentResult.status == "error"

Engines are mocked at their import path so no live services are needed.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.base import AgentRequest, AgentResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CLIENT_ID = uuid.uuid4()


def _req(**params) -> AgentRequest:
    return AgentRequest(client_id=_CLIENT_ID, params=params)


def _mock_session() -> MagicMock:
    s = MagicMock()
    s.scalar = AsyncMock(return_value=None)
    s.execute = AsyncMock(
        return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[]))))
    )
    s.commit = AsyncMock()
    s.add = MagicMock()
    return s


# ---------------------------------------------------------------------------
# CRM Agent
# ---------------------------------------------------------------------------

class TestCrmAgent:
    @pytest.mark.asyncio
    async def test_invoke_ok(self):
        session = _mock_session()
        dna_mock = MagicMock()
        dna_mock.id = uuid.uuid4()
        session.scalar = AsyncMock(return_value=dna_mock)

        with patch("app.agents.crm_agent.extract_dna", new=AsyncMock(return_value={"Alice": 1})):
            from app.agents import crm_agent
            result = await crm_agent.invoke(_req(), session)

        assert isinstance(result, AgentResult)
        assert result.agent == "crm"
        assert result.status == "ok"
        assert result.payload["extracted"] == {"Alice": 1}
        assert result.payload["dna_id"] == str(dna_mock.id)
        assert result.error is None

    @pytest.mark.asyncio
    async def test_invoke_error(self):
        session = _mock_session()

        with patch(
            "app.agents.crm_agent.extract_dna",
            new=AsyncMock(side_effect=RuntimeError("run /admin/seed/crm first")),
        ):
            from app.agents import crm_agent
            result = await crm_agent.invoke(_req(), session)

        assert result.status == "error"
        assert "seed/crm" in result.error
        assert result.payload == {}


# ---------------------------------------------------------------------------
# Portfolio Agent
# ---------------------------------------------------------------------------

class TestPortfolioAgent:
    @pytest.mark.asyncio
    async def test_invoke_ok(self):
        session = _mock_session()
        engine_out = {"clients_processed": 1, "proposals_written": 3}

        with patch("app.agents.portfolio_agent.compute_swaps", new=AsyncMock(return_value=engine_out)):
            from app.agents import portfolio_agent
            result = await portfolio_agent.invoke(_req(), session)

        assert result.status == "ok"
        assert result.payload == engine_out
        assert result.agent == "portfolio"

    @pytest.mark.asyncio
    async def test_invoke_error_missing_dna(self):
        session = _mock_session()

        with patch(
            "app.agents.portfolio_agent.compute_swaps",
            new=AsyncMock(side_effect=RuntimeError("run /admin/seed/dna first")),
        ):
            from app.agents import portfolio_agent
            result = await portfolio_agent.invoke(_req(), session)

        assert result.status == "error"
        assert "seed/dna" in result.error


# ---------------------------------------------------------------------------
# News Agent
# ---------------------------------------------------------------------------

class TestNewsAgent:
    @pytest.mark.asyncio
    async def test_invoke_ok(self):
        session = _mock_session()
        engine_out = {"matched": 5, "classified": 3, "inserted": 3}

        with patch(
            "app.agents.news_agent.scan_news_for_client", new=AsyncMock(return_value=engine_out)
        ):
            from app.agents import news_agent
            result = await news_agent.invoke(_req(), session)

        assert result.status == "ok"
        assert result.payload == engine_out
        assert result.agent == "news"

    @pytest.mark.asyncio
    async def test_invoke_error_missing_watchlist(self):
        session = _mock_session()

        with patch(
            "app.agents.news_agent.scan_news_for_client",
            new=AsyncMock(side_effect=RuntimeError("run /admin/seed/watchlist first")),
        ):
            from app.agents import news_agent
            result = await news_agent.invoke(_req(), session)

        assert result.status == "error"
        assert "watchlist" in result.error


# ---------------------------------------------------------------------------
# Message Agent
# ---------------------------------------------------------------------------

_DRAFT_ID = uuid.uuid4()

_RENDER_OUT = {
    "draft_id": str(_DRAFT_ID),
    "client_id": str(_CLIENT_ID),
    "preset": "balanced",
    "draft_text": "Dear Alice, ...",
    "facts_used": ["numbers.current_chf"],
    "provenance": [],
    "guardrail_passed": True,
}

_FS_OUT = {
    "draft_id": str(_DRAFT_ID),
    "client_id": str(_CLIENT_ID),
    "fact_sheet": {"numbers": {"current_chf": 100000}},
    "has_proposal": True,
}


class TestMessageAgent:
    @pytest.mark.asyncio
    async def test_invoke_ok_with_draft_id(self):
        """When draft_id is provided, skip assemble_fact_sheet and go straight to render."""
        session = _mock_session()

        with (
            patch("app.agents.message_agent.render_message_draft", new=AsyncMock(return_value=_RENDER_OUT)) as mock_render,
            patch("app.agents.message_agent.assemble_fact_sheet", new=AsyncMock(return_value=_FS_OUT)) as mock_fs,
        ):
            from app.agents import message_agent
            result = await message_agent.invoke(_req(draft_id=str(_DRAFT_ID)), session)

        assert result.status == "ok"
        assert result.payload["draft_id"] == str(_DRAFT_ID)
        assert result.payload["guardrail_passed"] is True
        mock_render.assert_called_once()
        mock_fs.assert_not_called()

    @pytest.mark.asyncio
    async def test_invoke_ok_without_draft_id_calls_assemble_first(self):
        """Without draft_id, the agent runs MSG2 (assemble) then MSG3 (render)."""
        session = _mock_session()

        with (
            patch("app.agents.message_agent.assemble_fact_sheet", new=AsyncMock(return_value=_FS_OUT)) as mock_fs,
            patch("app.agents.message_agent.render_message_draft", new=AsyncMock(return_value=_RENDER_OUT)) as mock_render,
        ):
            from app.agents import message_agent
            result = await message_agent.invoke(_req(), session)

        assert result.status == "ok"
        mock_fs.assert_called_once_with(session, _CLIENT_ID, alert_id=None)
        mock_render.assert_called_once()

    @pytest.mark.asyncio
    async def test_invoke_error_guardrail_rejection(self):
        session = _mock_session()

        with (
            patch("app.agents.message_agent.assemble_fact_sheet", new=AsyncMock(return_value=_FS_OUT)),
            patch(
                "app.agents.message_agent.render_message_draft",
                new=AsyncMock(side_effect=RuntimeError("MSG4 guardrail: draft contains numbers not found")),
            ),
        ):
            from app.agents import message_agent
            result = await message_agent.invoke(_req(), session)

        assert result.status == "error"
        assert "guardrail" in result.error

    @pytest.mark.asyncio
    async def test_invoke_error_missing_fact_sheet(self):
        session = _mock_session()

        with patch(
            "app.agents.message_agent.assemble_fact_sheet",
            new=AsyncMock(side_effect=RuntimeError("No open dna_conflict alert")),
        ):
            from app.agents import message_agent
            result = await message_agent.invoke(_req(), session)

        assert result.status == "error"
        assert "alert" in result.error
