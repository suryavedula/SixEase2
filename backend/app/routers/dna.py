"""Client DNA read endpoints (TASK-018, EPIC-04).

Exposes the structured ClientDNA profile with hydrated CRM-note sources for
traceability (G2) and widget/engine consumption (UC-18).
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.logging import get_logger
from app.models.citation import Citation
from app.models.derived import ClientDNA
from app.models.enums import SourceType
from app.models.source import Client, Interaction

router = APIRouter(prefix="/clients", tags=["dna"])
log = get_logger(__name__)


class DNASource(BaseModel):
    id: str
    date: str | None
    medium: str | None
    note: str | None


class DNAResponse(BaseModel):
    id: str
    client_id: str
    client_name: str
    mandate: str | None
    version: int
    values: list | None
    exclusions: list | None
    tilts: list | None
    life_events: list | None
    promises: list | None
    style_profile: dict | None
    business_context: str | None
    family_context: str | None
    temperament: str | None
    sources: list[DNASource]
    created_at: str
    updated_at: str


@router.get("/{client_id}/dna", response_model=DNAResponse)
async def get_client_dna(
    client_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> DNAResponse:
    """Return the ClientDNA profile with hydrated CRM-note sources for client_id.

    Sources are the de-duplicated Interaction rows cited by the DNA extraction,
    keyed by id so widget consumers can cross-reference each attribute's
    source_note_ids without a second request.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    dna = await session.scalar(
        select(ClientDNA).where(ClientDNA.client_id == client_id)
    )
    if dna is None:
        raise HTTPException(
            status_code=404,
            detail="DNA not found — run POST /admin/seed/dna first",
        )

    citations_result = await session.execute(
        select(Citation).where(
            Citation.owner_type == "client_dna",
            Citation.owner_id == dna.id,
            Citation.source_type == SourceType.CRM_NOTE,
        )
    )
    cited_ids = {c.source_id for c in citations_result.scalars().all()}

    sources: list[DNASource] = []
    if cited_ids:
        interactions_result = await session.execute(
            select(Interaction).where(Interaction.id.in_(cited_ids))
        )
        for interaction in interactions_result.scalars().all():
            sources.append(
                DNASource(
                    id=str(interaction.id),
                    date=str(interaction.date) if interaction.date else None,
                    medium=interaction.medium,
                    note=interaction.note,
                )
            )

    log.info(
        "dna.read",
        client_id=str(client_id),
        client_name=client.name,
        version=dna.version,
        sources=len(sources),
    )

    return DNAResponse(
        id=str(dna.id),
        client_id=str(dna.client_id),
        client_name=client.name,
        mandate=dna.mandate.value if dna.mandate else None,
        version=dna.version,
        values=dna.values,
        exclusions=dna.exclusions,
        tilts=dna.tilts,
        life_events=dna.life_events,
        promises=dna.promises,
        style_profile=dna.style_profile,
        business_context=dna.business_context,
        family_context=dna.family_context,
        temperament=dna.temperament,
        sources=sources,
        created_at=dna.created_at.isoformat(),
        updated_at=dna.updated_at.isoformat(),
    )
