"""Message draft read endpoints and MailHog test-send (TASK-039, EPIC-09).

MSG8 — channel is suggested at fact-sheet assembly time (loaders/fact_sheet.py).
MSG9 — one-click email handoff: GET /clients/{id}/drafts/latest returns the
       channel + draft; POST /drafts/{id}/send-test routes to MailHog for demo.

Never auto-sends — the send-test endpoint requires an explicit RM action
and routes to MailHog only (G1 / MSG7).
"""

import json
import uuid
from datetime import datetime
from email.message import EmailMessage

import aiosmtplib
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.logging import get_logger
from app.models.derived import MessageDraft
from app.models.enums import DraftStatus
from app.models.source import Client

router = APIRouter(tags=["messages"])
log = get_logger(__name__)
settings = get_settings()


class DraftOut(BaseModel):
    id: str
    client_id: str
    channel: str | None
    draft_text: str | None
    fact_sheet: dict | None
    facts_used: list | None
    provenance: list | None
    style: str | None
    status: str
    created_at: datetime
    updated_at: datetime | None


def _to_draft_out(draft: MessageDraft) -> DraftOut:
    return DraftOut(
        id=str(draft.id),
        client_id=str(draft.client_id),
        channel=draft.channel,
        draft_text=draft.draft_text,
        fact_sheet=draft.fact_sheet,
        facts_used=draft.facts_used,
        provenance=draft.provenance,
        style=draft.style,
        status=draft.status.value if hasattr(draft.status, "value") else draft.status,
        created_at=draft.created_at,
        updated_at=draft.updated_at,
    )


class DraftTextUpdate(BaseModel):
    draft_text: str


class SendTestResponse(BaseModel):
    status: str
    mailhog_ui: str


@router.get("/clients/{client_id}/drafts/latest", response_model=DraftOut)
async def get_latest_draft(
    client_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> DraftOut:
    """Return the most recent MessageDraft for a client (MSG8 / MSG9).

    Requires POST /admin/assemble/fact-sheet to have run first.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    draft = await session.scalar(
        select(MessageDraft)
        .where(MessageDraft.client_id == client_id)
        .order_by(MessageDraft.created_at.desc())
        .limit(1)
    )
    if draft is None:
        raise HTTPException(
            status_code=404,
            detail="No draft found — run POST /admin/assemble/fact-sheet first",
        )

    log.info("draft.read_latest", client_id=str(client_id), draft_id=str(draft.id))
    return _to_draft_out(draft)


@router.get("/drafts/{draft_id}", response_model=DraftOut)
async def get_draft(
    draft_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> DraftOut:
    """Return a specific MessageDraft by ID."""
    draft = await session.get(MessageDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    log.info("draft.read", draft_id=str(draft_id))
    return _to_draft_out(draft)


@router.patch("/drafts/{draft_id}", response_model=DraftOut)
async def patch_draft(
    draft_id: uuid.UUID,
    body: DraftTextUpdate,
    session: AsyncSession = Depends(get_session),
) -> DraftOut:
    """RM edits the draft text (TASK-040)."""
    draft = await session.get(MessageDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    draft.draft_text = body.draft_text
    await session.commit()
    log.info("draft.edited", draft_id=str(draft_id))
    return _to_draft_out(draft)


@router.post("/drafts/{draft_id}/approve")
async def approve_draft(
    draft_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """RM approves the draft; status → approved (TASK-040, MSG7)."""
    draft = await session.get(MessageDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")
    draft.status = DraftStatus.APPROVED
    await session.commit()
    log.info("draft.approved", draft_id=str(draft_id), client_id=str(draft.client_id))
    return {"id": str(draft.id), "status": draft.status.value}


@router.post("/drafts/{draft_id}/send-test", response_model=SendTestResponse)
async def send_test_draft(
    draft_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> SendTestResponse:
    """Send the draft to MailHog for demo testing (MSG9).

    Routes to mailhog:1025 only — never reaches a real email server.
    The RM must call this explicitly; nothing auto-sends (G1 / MSG7).
    Updates draft status to 'sent' after successful delivery.
    """
    draft = await session.get(MessageDraft, draft_id)
    if draft is None:
        raise HTTPException(status_code=404, detail="Draft not found")

    # Body: prefer rendered draft_text; fall back to fact_sheet JSON summary
    if draft.draft_text:
        body = draft.draft_text
    elif draft.fact_sheet:
        body = json.dumps(draft.fact_sheet, indent=2, ensure_ascii=False)
    else:
        body = "(No draft content yet — run LLM render first)"

    subject = "Advisory Update"
    if isinstance(draft.fact_sheet, dict) and draft.fact_sheet.get("trigger"):
        subject = f"Advisory: {draft.fact_sheet['trigger']}"

    msg = EmailMessage()
    msg["From"] = "rm@wealth.test"
    msg["To"] = "client@demo.test"
    msg["Subject"] = subject
    msg.set_content(body)

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.mailhog_host,
            port=settings.mailhog_smtp_port,
            start_tls=False,
        )
    except Exception as exc:
        log.error("draft.send_test_failed", draft_id=str(draft_id), error=str(exc))
        raise HTTPException(status_code=502, detail=f"MailHog send failed: {exc}") from exc

    draft.status = DraftStatus.SENT
    await session.commit()

    log.info(
        "draft.send_test_ok",
        draft_id=str(draft_id),
        client_id=str(draft.client_id),
        mailhog=f"{settings.mailhog_host}:{settings.mailhog_smtp_port}",
    )
    return SendTestResponse(
        status="sent",
        mailhog_ui=f"http://localhost:{settings.mailhog_ui_port}",
    )
