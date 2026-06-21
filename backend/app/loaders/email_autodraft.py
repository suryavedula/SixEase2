"""Auto-draft "the answer" for new inbound emails (TASK-062 Part A, EPIC-08).

Invoked from email_ingest for each NEW inbound thread. Routes by type (the RM's
choice — "both by type"):
  • client correspondence → a REPLY draft (loaders/email_reply)
  • a held instrument      → an ADVISORY draft (fact_sheet + message_render)
Persists a MessageDraft (served by /clients/{id}/drafts/latest) and a DONE Task
(source="email") so the prepared answer shows up in the RM's action surface. Draft
only — never sent (autonomy boundary G1).

Dedup: a Redis set of processed Graph message ids, so a thread is auto-drafted once
even though the radar rebuilds on every refresh cycle.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.graph_mail import GraphMessage
from app.loaders.change_radar import RadarSignal
from app.loaders.email_reply import draft_email_reply
from app.loaders.fact_sheet import assemble_fact_sheet
from app.loaders.message_render import render_message_draft
from app.logging import get_logger
from app.models.derived import Task
from app.models.enums import ExecutionMode, TaskStatus
from app.redis_client import redis_client

log = get_logger(__name__)

_SEEN_SET = "ms_graph:autodrafted"


async def _already_drafted(message_id: str) -> bool:
    """True if this message id was already auto-drafted; records it as seen if new."""
    added = await redis_client.sadd(_SEEN_SET, message_id)
    return added == 0


def _resolved(signals: list[RadarSignal], entity_type: str) -> RadarSignal | None:
    return next(
        (
            s
            for s in signals
            if s.entity_type == entity_type and not str(s.client_id).startswith("unmatched")
        ),
        None,
    )


async def autodraft_email(
    session: AsyncSession,
    rep: GraphMessage,
    signals: list[RadarSignal],
) -> str | None:
    """Pre-draft the answer for one new inbound email. Returns draft_id, or None when
    nothing was drafted (already seen, or no resolvable client)."""
    if not rep.id or await _already_drafted(rep.id):
        return None

    client_sig = _resolved(signals, "client")
    instrument_sig = _resolved(signals, "instrument")

    try:
        if client_sig is not None:
            cid = uuid.UUID(client_sig.client_id)
            res = await draft_email_reply(
                session, cid, rep.subject, rep.body_text, rep.from_name or rep.from_address
            )
            draft_id, kind, label = res["draft_id"], "reply", client_sig.entity_label
            title, summary = f"Prepared reply to {label}", res["draft_text"]
        elif instrument_sig is not None:
            cid = uuid.UUID(instrument_sig.client_id)
            fs = await assemble_fact_sheet(session, cid)
            draft_id = fs["draft_id"]
            render = await render_message_draft(session, uuid.UUID(draft_id))
            kind, label = "advisory", instrument_sig.entity_label
            title, summary = f"Prepared advisory on {label}", render.get("draft_text")
        else:
            return None  # unresolved / book-wide email → no single client to draft for
    except Exception as exc:  # noqa: BLE001 — a draft is optional; never break ingestion
        log.warning("email_autodraft.skip", message_id=rep.id, error=str(exc))
        return None

    task = Task(
        client_id=cid,
        title=title,
        source="email",
        execution_mode=ExecutionMode.AUTO,
        status=TaskStatus.DONE,
        result={"kind": kind, "draft_id": draft_id, "summary": summary, "trigger": rep.subject},
    )
    session.add(task)
    await session.commit()
    log.info("email_autodraft.created", kind=kind, client_id=str(cid), draft_id=draft_id)
    return draft_id
