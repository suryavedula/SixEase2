"""Demo scenario: an overnight client email → prepared answer (pitch demo only).

Pre-bakes the "a personal email arrived overnight" beat WITHOUT a live inbox, a
Microsoft sign-in, or the (slow) LLM classify of the real inbox. It writes three
rows directly:
  • a ChangeEvent (source="email") — the overnight life-event on the Change Radar
  • a DONE Task(source="email") carrying the prepared reply → "View answer"
  • a MessageDraft (the drafted reply) shown in the composer / Locked Facts panel

The ChangeEvent uses a pinned `entity_key` ("email:demo:%") that build_change_radar
deliberately does NOT delete, so the item survives the refresh loop. The real email
pipeline is untouched — this is purely additive demo data.

Idempotent: re-running refreshes the event and reuses the existing task/draft.
"""

import json
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.logging import get_logger
from app.models.derived import ChangeEvent, MessageDraft, Task
from app.models.enums import DraftStatus, ExecutionMode, TaskStatus
from app.models.source import Client, Position
from app.redis_client import redis_client

settings = get_settings()
log = get_logger(__name__)

_MARKER = "demo:divorce:artifacts"  # Redis: JSON {client_id, draft_id, task_id}
_ENTITY_PREFIX = "email:demo:divorce:"

_INCOMING_SUBJECT = "Personal update"
_INCOMING_EXCERPT = (
    "I wanted to let you know on a personal note that my divorce has now been "
    "finalised. It's been a hard few months. When you have time I'd value a "
    "conversation about what this means for my accounts and planning."
)
_DNA_NOTE = "Client shared a major life event (divorce) by email overnight — handle with care."
_SUGGESTED = "Reply with care, or call first"
_DRAFT_TEXT = (
    "Dear {name},\n\n"
    "Thank you for letting me know — I'm sorry it's been a difficult period, and "
    "I appreciate you sharing it with me.\n\n"
    "When you're ready, I'd suggest we set aside time to review a few things "
    "together: beneficiary designations, how your accounts are structured, and "
    "whether your current risk profile still reflects your plans. There's no "
    "urgency today — we'll go entirely at your pace.\n\n"
    "Would a short call next week suit you? I'm here whenever you'd like to talk.\n\n"
    "Warm regards,\nYour relationship manager"
)


async def resolve_demo_client(session: AsyncSession) -> Client | None:
    """The persona the scenario is anchored to (DEMO_EMAIL_CLIENT by name, else first)."""
    name = settings.demo_email_client.strip()
    if name:
        client = await session.scalar(select(Client).where(Client.name == name))
        if client is not None:
            return client
        log.warning("demo_email.client_not_found", name=name)
    return await session.scalar(select(Client).order_by(Client.name).limit(1))


async def _ensure_task_draft(session: AsyncSession, client: Client) -> tuple[str, str]:
    """Create the prepared draft + DONE task once; return (draft_id, task_id)."""
    raw = await redis_client.get(_MARKER)
    if raw:
        cached = json.loads(raw)
        if cached.get("client_id") == str(client.id):
            draft = await session.get(MessageDraft, uuid.UUID(cached["draft_id"]))
            task = await session.get(Task, uuid.UUID(cached["task_id"]))
            if draft is not None and task is not None:
                return cached["draft_id"], cached["task_id"]

    draft = MessageDraft(
        client_id=client.id,
        fact_sheet={
            "type": "email_reply",
            "incoming": {
                "subject": _INCOMING_SUBJECT,
                "from": client.name,
                "excerpt": _INCOMING_EXCERPT,
            },
            "subject": f"Re: {_INCOMING_SUBJECT}",
        },
        draft_text=_DRAFT_TEXT.format(name=client.name.split()[0]),
        style="balanced",
        channel="email",
        facts_used=["incoming.subject", "incoming.excerpt"],
        provenance=[
            {
                "fact_key": "incoming_email",
                "value": "Personal update — divorce finalised",
                "source": "Inbox (received overnight)",
            },
            {"fact_key": "client_dna", "value": "Major life event — divorce", "source": "Client DNA"},
        ],
        status=DraftStatus.DRAFT,
    )
    session.add(draft)
    await session.flush()

    task = Task(
        client_id=client.id,
        title="Prepared reply — personal update (overnight email)",
        source="email",
        execution_mode=ExecutionMode.AUTO,
        status=TaskStatus.DONE,
        result={
            "kind": "reply",
            "draft_id": str(draft.id),
            "summary": "Drafted a careful reply to the client's personal update.",
            "trigger": "Personal update — divorce",
        },
    )
    session.add(task)
    await session.flush()
    await redis_client.set(
        _MARKER,
        json.dumps({"client_id": str(client.id), "draft_id": str(draft.id), "task_id": str(task.id)}),
    )
    log.info("demo_email.task_draft_created", client=client.name, draft_id=str(draft.id))
    return str(draft.id), str(task.id)


async def ensure_demo_scenario(session: AsyncSession) -> dict:
    """Write (idempotently) the pinned radar event + task + draft for the demo."""
    client = await resolve_demo_client(session)
    if client is None:
        return {"created": False, "reason": "no client to anchor to"}

    draft_id, task_id = await _ensure_task_draft(session, client)

    total = float(
        await session.scalar(
            select(func.coalesce(func.sum(Position.current_chf), 0)).where(
                Position.client_id == client.id
            )
        )
        or 0.0
    )
    entity_key = f"{_ENTITY_PREFIX}{client.id}"
    overnight = datetime.now(timezone.utc) - timedelta(hours=8)

    # Upsert: drop any prior demo event for this client, then insert a fresh one.
    await session.execute(delete(ChangeEvent).where(ChangeEvent.entity_key == entity_key))
    session.add(
        ChangeEvent(
            action="Life event: divorce (email)",
            entity_key=entity_key,
            entity_type="client",
            entity_label=client.name,
            source="email",
            event_ts=overnight,
            magnitude=0.95,
            impact_score=total * 0.95 * 1.5,  # exposure × magnitude × dna_relevance
            client_count=1,
            total_exposure_chf=round(total, 2),
            impacted_clients=[
                {
                    "client_id": str(client.id),
                    "client_name": client.name,
                    "exposure_chf": round(total, 2),
                    "exposure_pct": 100.0,
                    "drift_caused": None,
                    "dna_note": _DNA_NOTE,
                    "suggested_action": _SUGGESTED,
                    "alert_id": None,
                    "swap_candidate": None,
                }
            ],
            suggested_batch_action=None,
            sources=[{"type": "email", "entity": entity_key, "signals": 1}],
            unresolved_reason=None,
        )
    )
    await session.commit()
    log.info("demo_email.scenario_ready", client=client.name, entity_key=entity_key)
    return {
        "created": True,
        "client": client.name,
        "draft_id": draft_id,
        "task_id": task_id,
        "entity_key": entity_key,
    }


async def reset_demo(session: AsyncSession) -> dict:
    """Remove the demo task + draft + pinned radar event(s) and clear the marker."""
    await session.execute(delete(ChangeEvent).where(ChangeEvent.entity_key.like(f"{_ENTITY_PREFIX}%")))
    raw = await redis_client.get(_MARKER)
    if raw:
        cached = json.loads(raw)
        for model, key in ((Task, "task_id"), (MessageDraft, "draft_id")):
            ident = cached.get(key)
            if ident:
                row = await session.get(model, uuid.UUID(ident))
                if row is not None:
                    await session.delete(row)
        await redis_client.delete(_MARKER)
    await session.commit()
    log.info("demo_email.reset")
    return {"reset": True}
