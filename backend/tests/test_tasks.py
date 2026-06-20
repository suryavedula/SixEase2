"""Unit tests for backend/app/routers/tasks.py (TASK-049, EPIC-12).

Tests call router handler functions directly with mocked AsyncSession —
same pattern as test_alert_noise.py. No real DB or Redis required.
"""

import uuid
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.models.enums import ExecutionMode, TaskStatus
from app.routers.tasks import (
    CreateTaskRequest,
    TaskTransitionRequest,
    create_task,
    get_client_tasks,
    transition_task,
)

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_CLIENT_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
_TASK_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")


def _make_client(client_id: uuid.UUID = _CLIENT_ID) -> MagicMock:
    c = MagicMock()
    c.id = client_id
    c.name = "Test Client"
    return c


def _make_task(
    task_id: uuid.UUID = _TASK_ID,
    client_id: uuid.UUID = _CLIENT_ID,
    source: str = "note",
    execution_mode: ExecutionMode = ExecutionMode.MANUAL,
    status: TaskStatus = TaskStatus.CREATED,
    title: str = "Test task",
) -> MagicMock:
    t = MagicMock()
    t.id = task_id
    t.client_id = client_id
    t.alert_id = None
    t.title = title
    t.source = source
    t.execution_mode = execution_mode
    t.status = status
    t.result = None
    t.created_at = datetime(2026, 6, 20, 12, 0, 0)
    return t


def _session_with_client(client: MagicMock | None = None) -> MagicMock:
    s = MagicMock()
    s.get = AsyncMock(return_value=client)
    s.execute = AsyncMock(return_value=MagicMock(scalars=MagicMock(return_value=MagicMock(all=MagicMock(return_value=[])))))
    s.add = MagicMock()
    s.commit = AsyncMock()
    s.refresh = AsyncMock()
    return s


# ---------------------------------------------------------------------------
# GET /clients/{client_id}/tasks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_tasks_returns_empty_list():
    client = _make_client()
    session = _session_with_client(client)

    resp = await get_client_tasks(client_id=_CLIENT_ID, status=None, mode=None, session=session)

    assert resp.client_id == str(_CLIENT_ID)
    assert resp.client_name == "Test Client"
    assert resp.tasks == []
    assert resp.total == 0


@pytest.mark.asyncio
async def test_get_tasks_returns_tasks():
    client = _make_client()
    task = _make_task()

    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = [task]
    session = _session_with_client(client)
    session.execute = AsyncMock(return_value=mock_result)

    resp = await get_client_tasks(client_id=_CLIENT_ID, status=None, mode=None, session=session)

    assert resp.total == 1
    assert resp.tasks[0].id == str(_TASK_ID)
    assert resp.tasks[0].source == "note"
    assert resp.tasks[0].execution_mode == "Manual"
    assert resp.tasks[0].status == "created"


@pytest.mark.asyncio
async def test_get_tasks_404_on_missing_client():
    session = _session_with_client(None)

    with pytest.raises(HTTPException) as exc_info:
        await get_client_tasks(client_id=_CLIENT_ID, status=None, mode=None, session=session)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_get_tasks_passes_status_filter():
    """Status filter is forwarded to the query (we verify execute is called once)."""
    client = _make_client()
    session = _session_with_client(client)

    await get_client_tasks(client_id=_CLIENT_ID, status="created", mode=None, session=session)

    session.execute.assert_awaited_once()


@pytest.mark.asyncio
async def test_get_tasks_passes_mode_filter():
    client = _make_client()
    session = _session_with_client(client)

    await get_client_tasks(client_id=_CLIENT_ID, status=None, mode="Auto", session=session)

    session.execute.assert_awaited_once()


# ---------------------------------------------------------------------------
# POST /clients/{client_id}/tasks
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_create_task_manual_note():
    client = _make_client()
    session = _session_with_client(client)

    async def _refresh(t):
        # Simulate what SQLAlchemy does after commit: populate server defaults
        t.id = _TASK_ID
        t.alert_id = None
        t.result = None
        t.created_at = datetime(2026, 6, 20, 12, 0, 0)

    session.refresh = AsyncMock(side_effect=_refresh)

    body = CreateTaskRequest(title="Follow up", source="note", execution_mode="Manual")

    with patch("app.routers.tasks.enqueue", new=AsyncMock()) as mock_enqueue:
        resp = await create_task(client_id=_CLIENT_ID, body=body, session=session)
        mock_enqueue.assert_not_awaited()

    session.add.assert_called_once()
    session.commit.assert_awaited_once()
    assert resp.status == "created"
    assert resp.source == "note"
    assert resp.execution_mode == "Manual"


@pytest.mark.asyncio
async def test_create_task_auto_promise_enqueues():
    client = _make_client()
    session = _session_with_client(client)

    # refresh sets task.id so _task_out can serialize it
    created_task: MagicMock | None = None

    def capture_add(t: MagicMock) -> None:
        nonlocal created_task
        t.id = _TASK_ID
        t.alert_id = None
        t.result = None
        t.created_at = datetime(2026, 6, 20, 12, 0, 0)
        t.execution_mode = ExecutionMode.AUTO
        t.status = TaskStatus.CREATED
        created_task = t

    session.add = MagicMock(side_effect=capture_add)
    session.refresh = AsyncMock()

    body = CreateTaskRequest(title="Research ESG", source="promise", execution_mode="Auto")

    with patch("app.routers.tasks.enqueue", new=AsyncMock()) as mock_enqueue:
        await create_task(client_id=_CLIENT_ID, body=body, session=session)
        mock_enqueue.assert_awaited_once_with(
            "task_queue",
            {"task_id": str(_TASK_ID), "client_id": str(_CLIENT_ID)},
        )


@pytest.mark.asyncio
async def test_create_task_rejects_alert_source():
    client = _make_client()
    session = _session_with_client(client)

    body = CreateTaskRequest(title="From alert", source="alert", execution_mode="Manual")

    with pytest.raises(HTTPException) as exc_info:
        await create_task(client_id=_CLIENT_ID, body=body, session=session)

    assert exc_info.value.status_code == 422
    assert "convert" in exc_info.value.detail.lower()


@pytest.mark.asyncio
async def test_create_task_rejects_bad_source():
    client = _make_client()
    session = _session_with_client(client)

    body = CreateTaskRequest(title="Bad", source="unknown_source", execution_mode="Manual")

    with pytest.raises(HTTPException) as exc_info:
        await create_task(client_id=_CLIENT_ID, body=body, session=session)

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_create_task_rejects_bad_execution_mode():
    client = _make_client()
    session = _session_with_client(client)

    body = CreateTaskRequest(title="Bad mode", source="note", execution_mode="Rogue")

    with pytest.raises(HTTPException) as exc_info:
        await create_task(client_id=_CLIENT_ID, body=body, session=session)

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_create_task_404_on_missing_client():
    session = _session_with_client(None)

    body = CreateTaskRequest(title="Task", source="note", execution_mode="Manual")

    with pytest.raises(HTTPException) as exc_info:
        await create_task(client_id=_CLIENT_ID, body=body, session=session)

    assert exc_info.value.status_code == 404


# ---------------------------------------------------------------------------
# PATCH /clients/{client_id}/tasks/{task_id}
# ---------------------------------------------------------------------------


def _session_for_patch(client: MagicMock | None, task: MagicMock | None) -> MagicMock:
    s = MagicMock()

    async def _get(model, pk):
        from app.models.derived import Task as TaskModel
        from app.models.source import Client as ClientModel
        if model is ClientModel:
            return client
        if model is TaskModel:
            return task
        return None

    s.get = AsyncMock(side_effect=_get)
    s.commit = AsyncMock()
    return s


@pytest.mark.asyncio
async def test_transition_created_to_running():
    client = _make_client()
    task = _make_task(status=TaskStatus.CREATED)
    session = _session_for_patch(client, task)

    body = TaskTransitionRequest(status="running")
    resp = await transition_task(client_id=_CLIENT_ID, task_id=_TASK_ID, body=body, session=session)

    assert task.status == TaskStatus.RUNNING
    assert resp.status == "running"
    session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_transition_created_to_closed():
    client = _make_client()
    task = _make_task(status=TaskStatus.CREATED)
    session = _session_for_patch(client, task)

    body = TaskTransitionRequest(status="closed")
    resp = await transition_task(client_id=_CLIENT_ID, task_id=_TASK_ID, body=body, session=session)

    assert task.status == TaskStatus.CLOSED
    assert resp.status == "closed"


@pytest.mark.asyncio
async def test_transition_running_to_done_with_result():
    client = _make_client()
    task = _make_task(status=TaskStatus.RUNNING)
    session = _session_for_patch(client, task)

    result_payload = {"summary": "Found 3 ESG alternatives", "sources": ["CIO list"]}
    body = TaskTransitionRequest(status="done", result=result_payload)
    resp = await transition_task(client_id=_CLIENT_ID, task_id=_TASK_ID, body=body, session=session)

    assert task.status == TaskStatus.DONE
    assert task.result == result_payload
    assert resp.status == "done"


@pytest.mark.asyncio
async def test_transition_running_to_closed():
    client = _make_client()
    task = _make_task(status=TaskStatus.RUNNING)
    session = _session_for_patch(client, task)

    body = TaskTransitionRequest(status="closed")
    resp = await transition_task(client_id=_CLIENT_ID, task_id=_TASK_ID, body=body, session=session)

    assert task.status == TaskStatus.CLOSED


@pytest.mark.asyncio
async def test_transition_done_to_closed():
    client = _make_client()
    task = _make_task(status=TaskStatus.DONE)
    session = _session_for_patch(client, task)

    body = TaskTransitionRequest(status="closed")
    resp = await transition_task(client_id=_CLIENT_ID, task_id=_TASK_ID, body=body, session=session)

    assert task.status == TaskStatus.CLOSED


@pytest.mark.asyncio
async def test_transition_created_to_done_is_invalid():
    """created → done skips running — 409 Conflict."""
    client = _make_client()
    task = _make_task(status=TaskStatus.CREATED)
    session = _session_for_patch(client, task)

    body = TaskTransitionRequest(status="done")
    with pytest.raises(HTTPException) as exc_info:
        await transition_task(client_id=_CLIENT_ID, task_id=_TASK_ID, body=body, session=session)

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_transition_closed_is_terminal():
    """closed → anything is 409."""
    client = _make_client()
    task = _make_task(status=TaskStatus.CLOSED)
    session = _session_for_patch(client, task)

    for target in ("running", "done", "closed"):
        body = TaskTransitionRequest(status=target)
        with pytest.raises(HTTPException) as exc_info:
            await transition_task(client_id=_CLIENT_ID, task_id=_TASK_ID, body=body, session=session)
        assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_transition_unknown_status_422():
    client = _make_client()
    task = _make_task(status=TaskStatus.CREATED)
    session = _session_for_patch(client, task)

    body = TaskTransitionRequest(status="nonexistent")
    with pytest.raises(HTTPException) as exc_info:
        await transition_task(client_id=_CLIENT_ID, task_id=_TASK_ID, body=body, session=session)

    assert exc_info.value.status_code == 422


@pytest.mark.asyncio
async def test_transition_404_on_missing_client():
    task = _make_task()
    session = _session_for_patch(None, task)

    body = TaskTransitionRequest(status="running")
    with pytest.raises(HTTPException) as exc_info:
        await transition_task(client_id=_CLIENT_ID, task_id=_TASK_ID, body=body, session=session)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_transition_404_on_missing_task():
    client = _make_client()
    session = _session_for_patch(client, None)

    body = TaskTransitionRequest(status="running")
    with pytest.raises(HTTPException) as exc_info:
        await transition_task(client_id=_CLIENT_ID, task_id=_TASK_ID, body=body, session=session)

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_transition_404_when_task_belongs_to_other_client():
    client = _make_client(_CLIENT_ID)
    other_client_id = uuid.UUID("00000000-0000-0000-0000-000000000099")
    task = _make_task(client_id=other_client_id)  # different owner
    session = _session_for_patch(client, task)

    body = TaskTransitionRequest(status="running")
    with pytest.raises(HTTPException) as exc_info:
        await transition_task(client_id=_CLIENT_ID, task_id=_TASK_ID, body=body, session=session)

    assert exc_info.value.status_code == 404
