"""Email reply drafting (TASK-062 Part A, EPIC-08/EPIC-09).

When a new inbound client email lands on the radar, draft a *reply* grounded in the
client's DNA + recent CRM history. Distinct from fact_sheet.py (which drafts an
advisory about a holding): this answers what the client actually wrote.

Draft only — the RM reviews, edits, and sends (autonomy boundary G1). No figures are
authored: the prompt forbids inventing numbers, since no locked fact sheet backs a reply.

Public API:
    draft_email_reply(session, client_id, incoming_subject, incoming_body, sender) → dict
"""

import uuid

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import json_chat
from app.logging import get_logger
from app.models.derived import ClientDNA, MessageDraft
from app.models.enums import DraftStatus
from app.models.source import Client, Interaction

log = get_logger(__name__)


class _ReplyOut(BaseModel):
    subject: str
    draft_text: str


_SYSTEM = (
    "You are a relationship manager's assistant drafting a REPLY to a client's email. "
    "Write a warm, professional reply in the RM's voice, grounded in the client's known "
    "values and recent history. Acknowledge what they wrote and propose a clear next step. "
    "HARD RULES: do NOT invent figures, prices, returns, performance numbers, dates, or "
    "product names — speak qualitatively and offer to follow up with specifics. Keep it "
    "concise (under 180 words). Output ONLY JSON: {\"subject\": \"...\", \"draft_text\": \"...\"}."
)


async def draft_email_reply(
    session: AsyncSession,
    client_id: uuid.UUID,
    incoming_subject: str | None,
    incoming_body: str | None,
    sender_name: str | None,
) -> dict:
    """Draft a reply to a client email and persist it as a MessageDraft (status=DRAFT)."""
    client = await session.get(Client, client_id)
    dna = await session.scalar(select(ClientDNA).where(ClientDNA.client_id == client_id))
    interactions = (
        await session.execute(
            select(Interaction)
            .where(Interaction.client_id == client_id)
            .order_by(Interaction.date.desc())
            .limit(5)
        )
    ).scalars().all()

    dna_summary = ""
    if dna:
        dna_summary = (
            f"Values: {dna.values or []}\n"
            f"Exclusions: {dna.exclusions or []}\n"
            f"Tilts: {dna.tilts or []}\n"
            f"Temperament: {dna.temperament or ''}"
        )
    history = (
        "\n".join(f"- [{i.date}] {i.note}" for i in interactions if i.note) or "(no prior notes)"
    )

    user = (
        f"Client: {client.name if client else 'the client'}\n"
        f"Their email subject: {incoming_subject or '(none)'}\n"
        f"Their message:\n{(incoming_body or '')[:1500]}\n\n"
        f"Client DNA:\n{dna_summary}\n\n"
        f"Recent history:\n{history}"
    )
    out = await json_chat(
        [{"role": "system", "content": _SYSTEM}, {"role": "user", "content": user}],
        _ReplyOut,
        max_tokens=600,
    )

    fact_sheet = {
        "type": "email_reply",
        "incoming": {
            "subject": incoming_subject,
            "from": sender_name,
            "excerpt": (incoming_body or "")[:300],
        },
        "subject": out.subject,
    }
    provenance = [
        {
            "fact_key": "incoming_email",
            "value": incoming_subject or "",
            "source": "Microsoft Graph inbox",
        }
    ]
    if dna:
        provenance.append(
            {"fact_key": "client_dna", "value": f"v{dna.version}", "source": "ClientDNA"}
        )

    draft = MessageDraft(
        client_id=client_id,
        fact_sheet=fact_sheet,
        draft_text=out.draft_text,
        style="balanced",
        channel="email",
        facts_used=["incoming.subject", "incoming.excerpt"],
        provenance=provenance,
        status=DraftStatus.DRAFT,
    )
    session.add(draft)
    await session.flush()  # assign draft.id (caller commits)
    log.info("email_reply.drafted", client_id=str(client_id), draft_id=str(draft.id))
    return {"draft_id": str(draft.id), "draft_text": out.draft_text, "subject": out.subject}
