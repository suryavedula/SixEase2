"""Unit tests for the swap-decision endpoint (HITL persistence).

Calls the router handler directly with a mocked AsyncSession — same pattern as
tests/test_tasks.py. No real DB required. Verifies that an RM approve/reject is
persisted as a MANUAL Task with the swap set snapshotted into result.
"""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from app.models.enums import ExecutionMode, TaskStatus
from app.routers.portfolio import SwapDecisionRequest, decide_portfolio_swaps

_CLIENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


def _make_client() -> MagicMock:
    c = MagicMock()
    c.id = _CLIENT_ID
    c.name = "Test Client"
    return c


def _session(client: MagicMock | None, rows: list | None = None) -> MagicMock:
    s = MagicMock()
    s.get = AsyncMock(return_value=client)
    s.execute = AsyncMock(
        return_value=MagicMock(all=MagicMock(return_value=rows or []))
    )
    s.add = MagicMock()
    s.commit = AsyncMock()
    s.refresh = AsyncMock()
    return s


@pytest.mark.asyncio
async def test_approve_creates_manual_task():
    session = _session(_make_client())

    resp = await decide_portfolio_swaps(
        client_id=_CLIENT_ID,
        body=SwapDecisionRequest(decision="approved"),
        session=session,
    )

    assert resp.decision == "approved"
    assert resp.status == TaskStatus.CREATED.value
    assert resp.proposal_count == 0
    session.add.assert_called_once()
    session.commit.assert_awaited_once()
    # The persisted row is a MANUAL, source="swap" task carrying the decision.
    task = session.add.call_args.args[0]
    assert task.source == "swap"
    assert task.execution_mode == ExecutionMode.MANUAL
    assert task.result["decision"] == "approved"


@pytest.mark.asyncio
async def test_reject_is_recorded():
    session = _session(_make_client())

    resp = await decide_portfolio_swaps(
        client_id=_CLIENT_ID,
        body=SwapDecisionRequest(decision="rejected", notes="not now"),
        session=session,
    )

    assert resp.decision == "rejected"
    task = session.add.call_args.args[0]
    assert task.result["notes"] == "not now"


@pytest.mark.asyncio
async def test_invalid_decision_422():
    session = _session(_make_client())

    with pytest.raises(HTTPException) as exc:
        await decide_portfolio_swaps(
            client_id=_CLIENT_ID,
            body=SwapDecisionRequest(decision="maybe"),
            session=session,
        )
    assert exc.value.status_code == 422


@pytest.mark.asyncio
async def test_404_on_missing_client():
    session = _session(None)

    with pytest.raises(HTTPException) as exc:
        await decide_portfolio_swaps(
            client_id=_CLIENT_ID,
            body=SwapDecisionRequest(decision="approved"),
            session=session,
        )
    assert exc.value.status_code == 404


@pytest.mark.asyncio
async def test_snapshots_proposals_into_result():
    proposal = MagicMock(candidate_isin="CH123", candidate_valor="645156", fit_gain=0.2)
    position = MagicMock(issuer="Acme", security="Acme AG")
    position.id = uuid.uuid4()
    cio = MagicMock(issuer="Acme")
    session = _session(_make_client(), rows=[(proposal, position, cio)])

    resp = await decide_portfolio_swaps(
        client_id=_CLIENT_ID,
        body=SwapDecisionRequest(decision="approved"),
        session=session,
    )

    assert resp.proposal_count == 1
    task = session.add.call_args.args[0]
    assert task.result["proposals"][0]["candidate_isin"] == "CH123"
    assert task.result["proposals"][0]["issuer"] == "Acme"
