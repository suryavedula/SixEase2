"""Voice-note CRM write-back and audio storage (TASK-048, EPIC-11).

On RM approval of a voice-dictated note (produced by TASK-047) two endpoints
handle the persistence:

  POST /clients/{id}/voice-notes/audio   — multipart upload → MinIO; returns audio_key
  POST /clients/{id}/voice-notes/commit  — writes Interaction + applies DNA delta

The split lets the frontend upload audio in the background while the RM reviews
the structured note; the commit is then a cheap metadata-only call.

Never auto-commits — both endpoints require explicit RM action (G1).
"""

import asyncio
import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.loaders.dna import apply_dna_delta
from app.logging import get_logger
from app.models.source import Client, Interaction
from app.storage import put_object

router = APIRouter(prefix="/clients", tags=["voice"])
log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Request / response models
# ---------------------------------------------------------------------------


class NoteIn(BaseModel):
    date: str | None = None          # ISO date string (YYYY-MM-DD); defaults to today
    medium: str = "VoiceNote"
    rm_name: str | None = None
    client_contact: str | None = None
    body: str                        # structured note text from TASK-047


class DnaDelta(BaseModel):
    values: list[dict] = []
    exclusions: list[dict] = []
    tilts: list[dict] = []
    life_events: list[dict] = []
    promises: list[dict] = []


class CommitRequest(BaseModel):
    note: NoteIn
    dna_delta: DnaDelta = DnaDelta()
    audio_key: str | None = None     # MinIO key from /audio upload; None = no recording


class CommitResponse(BaseModel):
    interaction_id: str
    dna_version: int | None
    audio_key: str | None


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/{client_id}/voice-notes/audio")
async def upload_voice_audio(
    client_id: uuid.UUID,
    file: UploadFile,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Store raw audio bytes in MinIO and return the object key.

    Called by the TASK-047 voice UI before (or during) RM review; the returned
    audio_key is passed to /commit on approval. Content-type defaults to
    audio/webm when the browser omits it.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio file")

    key = f"voice-notes/{client_id}/{file.filename or 'recording.webm'}"
    content_type = file.content_type or "audio/webm"

    # put_object is synchronous (MinIO SDK) — offload to thread pool.
    await asyncio.to_thread(put_object, key, data, content_type)

    log.info(
        "voice.audio_uploaded",
        client_id=str(client_id),
        key=key,
        bytes=len(data),
        content_type=content_type,
    )
    return {"audio_key": key}


@router.post("/{client_id}/voice-notes/commit", response_model=CommitResponse)
async def commit_voice_note(
    client_id: uuid.UUID,
    body: CommitRequest,
    session: AsyncSession = Depends(get_session),
) -> CommitResponse:
    """Write-back an approved voice note to the CRM store and apply DNA delta.

    Three effects in one transaction:
    1. New Interaction row (CRM write-back, G7)
    2. audio_key stamped on the Interaction (links MinIO object to the note)
    3. DNA delta appended to ClientDNA + version bumped (with Citation for G2)

    Prerequisites: /admin/seed/crm and /admin/seed/dna must have run.
    If dna_delta is empty all lists are empty the DNA update is skipped.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    note_date: date | None = None
    if body.note.date:
        try:
            note_date = date.fromisoformat(body.note.date)
        except ValueError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid date format '{body.note.date}' — use YYYY-MM-DD",
            )

    interaction = Interaction(
        client_id=client_id,
        date=note_date,
        medium=body.note.medium,
        rm_name=body.note.rm_name,
        client_contact=body.note.client_contact,
        note=body.note.body,
        audio_key=body.audio_key,
    )
    session.add(interaction)
    await session.flush()  # assign interaction.id before passing to apply_dna_delta

    delta_dict = body.dna_delta.model_dump()
    has_delta = any(delta_dict.values())

    dna_version: int | None = None
    if has_delta:
        try:
            dna_version = await apply_dna_delta(
                session, client_id, delta_dict, interaction.id
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    await session.commit()

    log.info(
        "voice.commit",
        client_id=str(client_id),
        interaction_id=str(interaction.id),
        dna_version=dna_version,
        audio_key=body.audio_key,
        delta_keys=[k for k, v in delta_dict.items() if v],
    )

    return CommitResponse(
        interaction_id=str(interaction.id),
        dna_version=dna_version,
        audio_key=body.audio_key,
    )
