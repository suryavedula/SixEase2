"""Task queue endpoints (TASK-049, EPIC-12) — §19.2 TK1/TK2/TK6.

Exposes the per-client task list and task lifecycle write endpoints.

Tasks are created three ways:
  1. From an alert: POST /clients/{id}/alerts/{alert_id}/convert (alerts.py, TASK-035)
  2. From a note or promise: POST /clients/{id}/tasks (this router)
  3. Future: automatically by the research-agent pipeline (TASK-043+)

Auto-mode tasks (TK2) are enqueued to the Redis "task_queue" list on creation;
the research-task runner (TASK-043+) dequeues and executes them.
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.logging import get_logger
from app.models.derived import Task
from app.models.enums import ExecutionMode, TaskStatus
from app.models.source import Client
from app.redis_client import enqueue

router = APIRouter(prefix="/clients", tags=["tasks"])
log = get_logger(__name__)

_VALID_SOURCES = frozenset({"note", "promise"})
_VALID_TRANSITIONS: dict[TaskStatus, frozenset[TaskStatus]] = {
    TaskStatus.CREATED: frozenset({TaskStatus.RUNNING, TaskStatus.CLOSED}),
    TaskStatus.RUNNING: frozenset({TaskStatus.DONE, TaskStatus.CLOSED}),
    TaskStatus.DONE: frozenset({TaskStatus.CLOSED}),
    TaskStatus.CLOSED: frozenset(),
}


class TaskOut(BaseModel):
    id: str
    client_id: str | None
    alert_id: str | None
    title: str | None
    source: str | None
    execution_mode: str
    status: str
    result: dict | None
    created_at: datetime


class TasksResponse(BaseModel):
    client_id: str
    client_name: str
    tasks: list[TaskOut]
    total: int


def _task_out(t: Task) -> TaskOut:
    return TaskOut(
        id=str(t.id),
        client_id=str(t.client_id) if t.client_id else None,
        alert_id=str(t.alert_id) if t.alert_id else None,
        title=t.title,
        source=t.source,
        execution_mode=t.execution_mode.value if hasattr(t.execution_mode, "value") else t.execution_mode,
        status=t.status.value if hasattr(t.status, "value") else t.status,
        result=t.result,
        created_at=t.created_at,
    )


@router.get("/{client_id}/tasks", response_model=TasksResponse)
async def get_client_tasks(
    client_id: uuid.UUID,
    status: str | None = Query(default=None, description="Filter by status: created, running, done, closed"),
    mode: str | None = Query(default=None, description="Filter by execution_mode: Auto, Manual"),
    session: AsyncSession = Depends(get_session),
) -> TasksResponse:
    """Return the task queue for a client, ordered by created_at DESC (TK1/TK6)."""
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    stmt = (
        select(Task)
        .where(Task.client_id == client_id)
        .order_by(Task.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(Task.status == status)
    if mode is not None:
        stmt = stmt.where(Task.execution_mode == mode)

    rows = (await session.execute(stmt)).scalars().all()

    log.info(
        "tasks.read",
        client_id=str(client_id),
        client_name=client.name,
        total=len(rows),
        status_filter=status,
        mode_filter=mode,
    )

    return TasksResponse(
        client_id=str(client_id),
        client_name=client.name,
        tasks=[_task_out(t) for t in rows],
        total=len(rows),
    )


class CreateTaskRequest(BaseModel):
    title: str
    source: str  # "note" | "promise"
    execution_mode: str = "Manual"  # "Auto" | "Manual"


@router.post("/{client_id}/tasks", response_model=TaskOut, status_code=201)
async def create_task(
    client_id: uuid.UUID,
    body: CreateTaskRequest,
    session: AsyncSession = Depends(get_session),
) -> TaskOut:
    """Create a task from a note or promise (TK1).

    source must be "note" or "promise". To create from an alert use
    POST /clients/{id}/alerts/{alert_id}/convert.
    Auto-mode tasks are enqueued to Redis for autonomous execution (TK2/TK3).
    """
    if body.source not in _VALID_SOURCES:
        raise HTTPException(
            status_code=422,
            detail=f"source must be one of {sorted(_VALID_SOURCES)}; use /convert for alert tasks",
        )

    mode_map = {m.value: m for m in ExecutionMode}
    exec_mode = mode_map.get(body.execution_mode)
    if exec_mode is None:
        raise HTTPException(status_code=422, detail=f"execution_mode must be Auto or Manual")

    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    task = Task(
        client_id=client.id,
        title=body.title,
        source=body.source,
        execution_mode=exec_mode,
        status=TaskStatus.CREATED,
    )
    session.add(task)
    await session.commit()
    await session.refresh(task)

    if exec_mode == ExecutionMode.AUTO:
        await enqueue("task_queue", {"task_id": str(task.id), "client_id": str(client.id)})
        log.info("task.enqueued", task_id=str(task.id), client_id=str(client_id))

    log.info(
        "task.created",
        task_id=str(task.id),
        client_id=str(client_id),
        source=body.source,
        execution_mode=exec_mode.value,
    )

    return _task_out(task)


class TaskTransitionRequest(BaseModel):
    status: str
    result: dict | None = None


@router.patch("/{client_id}/tasks/{task_id}", response_model=TaskOut)
async def transition_task(
    client_id: uuid.UUID,
    task_id: uuid.UUID,
    body: TaskTransitionRequest,
    session: AsyncSession = Depends(get_session),
) -> TaskOut:
    """Advance a task through its lifecycle (TK6): created→running→done/closed.

    result (JSONB) may be supplied when transitioning to done; it carries the
    cited brief / research output (TK4/TK5, G2).
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    task = await session.get(Task, task_id)
    if task is None or task.client_id != client_id:
        raise HTTPException(status_code=404, detail="Task not found")

    status_map = {s.value: s for s in TaskStatus}
    new_status = status_map.get(body.status)
    if new_status is None:
        raise HTTPException(status_code=422, detail=f"Unknown status: {body.status}")

    allowed = _VALID_TRANSITIONS.get(task.status, frozenset())
    if new_status not in allowed:
        raise HTTPException(
            status_code=409,
            detail=f"Cannot transition from {task.status.value} to {body.status}",
        )

    task.status = new_status
    if body.result is not None:
        task.result = body.result
    await session.commit()

    log.info(
        "task.transition",
        task_id=str(task_id),
        client_id=str(client_id),
        new_status=body.status,
    )

    return _task_out(task)
