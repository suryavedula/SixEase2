"""CRM Agent — delegates to the DNA Builder engine (TASK-054 / EPIC-13).

ST5 mapping: CRM Agent → DNA Builder (loaders/dna.py:extract_dna).

Extracts structured client DNA from CRM interaction notes and stores it in
client_dna. Requires /admin/seed/crm to have run first.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.base import AgentRequest, AgentResult
from app.loaders.dna import extract_dna
from app.logging import get_logger
from app.models.derived import ClientDNA

log = get_logger(__name__)


async def invoke(request: AgentRequest, session: AsyncSession) -> AgentResult:
    """Extract DNA for the given client and return the resulting DNA row id."""
    client_id = request.client_id
    log.info("agent.invoke.start", agent="crm", client_id=str(client_id))

    try:
        extracted = await extract_dna(session, client_id=client_id)

        dna_row = await session.scalar(
            select(ClientDNA).where(ClientDNA.client_id == client_id)
        )
        dna_id = str(dna_row.id) if dna_row else None

        log.info(
            "agent.invoke.done",
            agent="crm",
            client_id=str(client_id),
            dna_id=dna_id,
        )
        return AgentResult(
            agent="crm",
            client_id=client_id,
            status="ok",
            payload={"extracted": extracted, "dna_id": dna_id},
        )

    except Exception as exc:  # noqa: BLE001
        log.error("agent.invoke.error", agent="crm", client_id=str(client_id), error=str(exc))
        return AgentResult(
            agent="crm",
            client_id=client_id,
            status="error",
            payload={},
            error=str(exc),
        )
