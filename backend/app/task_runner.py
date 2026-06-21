"""Autonomous task runner (TASK-043, EPIC-12) — the consumer for `task_queue`.

The task router (routers/tasks.py) enqueues Auto-mode tasks to the Redis
`task_queue` list on creation (TK2). This background consumer dequeues them and
runs each through the LangGraph domain-agent orchestrator (EPIC-13), then writes
the cited result back onto the Task row for RM review (TK4/TK5).

Autonomy boundary (TK3, G1): the graph's `route_intent` node blocks manual-only
kinds (contact_client, place_order, send_message, crm_writeback) from running, and
no agent takes an outward/irreversible action — research and drafts only. A blocked
or failed task is closed with an explanatory `result.error`, never silently dropped.

Lifecycle (from main.py):
    task = start_task_runner()    # startup
    await stop_task_runner(task)  # shutdown

Mirrors the news_fanout consumer pattern: dequeue blocks 1s when empty (natural
back-pressure), so the loop needs no sleep.
"""

import asyncio
import contextlib
import uuid

from app.agents import graph
from app.db import SessionFactory
from app.logging import get_logger
from app.models.derived import Task
from app.models.enums import TaskStatus
from app.redis_client import dequeue

log = get_logger(__name__)

_TASK_QUEUE = "task_queue"


def _normalize_result(raw: dict, trace: list) -> dict:
    """Flatten the per-agent graph output into a presentation-friendly shape.

    The orchestrator nests output under the domain key that ran (crm / portfolio /
    news / message). The UI renders a generic brief, so we surface a top-level
    `summary`, `citations` ({source, text}), and `provenance` while keeping the
    raw payload + execution trace for traceability (G2).
    """
    out: dict = {**raw, "trace": trace}

    crm = raw.get("crm")
    if isinstance(crm, dict):  # research / analysis → cited brief
        out["kind"] = "research"
        out["summary"] = crm.get("summary")
        out["citations"] = [
            {"source": str(c), "text": ""} for c in (crm.get("citations") or [])
        ]
        out["recommendations"] = crm.get("recommendations") or []
        out["provenance"] = {
            "notes_read": crm.get("notes_read"),
            "articles_fetched": crm.get("articles_fetched"),
        }
        return out

    portfolio = raw.get("portfolio")
    if isinstance(portfolio, dict):  # swap candidates / fit
        out["kind"] = "portfolio"
        n = len(portfolio.get("swaps") or portfolio.get("candidates") or [])
        fit = portfolio.get("fit") or portfolio.get("fit_score")
        bits = []
        if fit is not None:
            bits.append(f"Portfolio fit {fit}")
        bits.append(f"{n} swap candidate(s) identified")
        out["summary"] = "; ".join(bits)
        out["citations"] = []
        return out

    news = raw.get("news")
    if isinstance(news, dict):  # news gather
        out["kind"] = "news"
        out["summary"] = (
            f"Matched {news.get('matched', 0)} article(s); "
            f"{news.get('inserted', 0)} new item(s) added to the radar."
        )
        out["citations"] = []
        return out

    message = raw.get("message")
    if isinstance(message, dict):  # draft prep
        out["kind"] = "message"
        out["summary"] = message.get("draft_text")
        out["citations"] = []
        out["draft_id"] = message.get("draft_id")
        return out

    return out


async def run_one_task() -> dict:
    """Dequeue one Auto task and execute it through the orchestrator.

    Returns a small status dict for observability. Idempotent against re-delivery:
    only tasks still in CREATED are run (a task already running/done/closed is
    skipped). The result JSONB carries the agent output plus its execution trace.
    """
    payload = await dequeue(_TASK_QUEUE, timeout=1)
    if payload is None:
        return {"task": None}

    task_id_str = payload.get("task_id")
    if not task_id_str:
        log.warning("task_runner.bad_payload", payload=payload)
        return {"task": None, "status": "bad_payload"}

    # 1. Claim the task: CREATED → RUNNING in a short transaction.
    async with SessionFactory() as session:
        task = await session.get(Task, uuid.UUID(task_id_str))
        if task is None:
            log.warning("task_runner.missing", task_id=task_id_str)
            return {"task": task_id_str, "status": "missing"}
        if task.status != TaskStatus.CREATED:
            # Already claimed/handled (re-delivery or a manual transition) — skip.
            return {"task": task_id_str, "status": "skipped", "current": task.status.value}

        client_id = str(task.client_id) if task.client_id else None
        title = task.title or ""
        task.status = TaskStatus.RUNNING
        await session.commit()

    log.info("task_runner.start", task_id=task_id_str, client_id=client_id, title=title)

    # 2. Run the graph (no DB transaction held; agents open their own sessions).
    #    task_kind is the free-form title — route_intent classifies it into a
    #    TaskKind and enforces the autonomy boundary before any agent runs.
    final = await graph.ainvoke(
        {
            "task_id": task_id_str,
            "task_kind": title or "research",
            "client_id": client_id,
            "input": title,
            "result": {},
            "trace": [],
            "error": None,
        }
    )

    # 3. Persist the outcome.
    async with SessionFactory() as session:
        task = await session.get(Task, uuid.UUID(task_id_str))
        if task is None:  # deleted mid-flight
            return {"task": task_id_str, "status": "missing"}

        trace = final.get("trace", [])
        if final.get("error"):
            task.status = TaskStatus.CLOSED
            task.result = {"error": final["error"], "trace": trace}
            log.warning("task_runner.failed", task_id=task_id_str, error=final["error"])
            outcome = "closed"
        else:
            task.status = TaskStatus.DONE
            task.result = _normalize_result(final.get("result") or {}, trace)
            log.info("task_runner.done", task_id=task_id_str)
            outcome = "done"
        await session.commit()

    return {"task": task_id_str, "status": outcome}


async def _runner_loop() -> None:
    """Continuous consumer: dequeue → run → repeat. dequeue blocks 1s when empty."""
    log.info("task_runner.started")
    while True:
        try:
            await run_one_task()
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # never let one bad task kill the loop
            log.warning("task_runner.cycle_error", error=str(exc))
            await asyncio.sleep(1)  # avoid a tight crash loop


def start_task_runner() -> "asyncio.Task[None]":
    """Spawn the task-queue consumer as a named asyncio background task."""
    return asyncio.create_task(_runner_loop(), name="task-runner")


async def stop_task_runner(task: "asyncio.Task[None]") -> None:
    """Cancel the task-queue consumer and wait for it to finish."""
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    log.info("task_runner.stopped")
