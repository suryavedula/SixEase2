"""Voice-note CRM write-back, structuring, and audio storage (TASK-047/048, EPIC-11).

Three endpoints:

  POST /clients/{id}/voice-notes/structure — transcript → structured draft (TASK-047)
  POST /clients/{id}/voice-notes/audio    — multipart upload → MinIO (TASK-048)
  POST /clients/{id}/voice-notes/commit   — writes Interaction + DNA delta (TASK-048)

/structure is a pure draft — it never writes to the database (G1). The RM reviews
the result and explicitly calls /commit on approval.
"""

import asyncio
import uuid
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.graph_auth import NotSignedInError
from app.graph_mail import create_calendar_event, send_via_graph
from app.loaders.dna import apply_dna_delta
from app.loaders.note_structure import NoteStructureOutput, structure_note
from app.loaders.task_classify import classify_execution_mode
from app.loaders.transcribe import transcribe_audio
from app.logging import get_logger
from app.models.enums import ExecutionMode, TaskKind
from app.models.source import Client, Interaction
from app.storage import put_object

router = APIRouter(prefix="/clients", tags=["voice"])
settings = get_settings()
# Client-agnostic dictation (no DB, no MinIO) — powers the command-dock mic, which
# transcribes free speech into the query box before any client is in focus.
dictation_router = APIRouter(prefix="/voice", tags=["voice"])
log = get_logger(__name__)


class DictationResponse(BaseModel):
    transcript: str


@dictation_router.post("/transcribe", response_model=DictationResponse)
async def transcribe_dictation(file: UploadFile) -> DictationResponse:
    """Transcribe a recorded clip to text via Whisper — no storage, no client.

    Used by the command dock's mic for general dictation (replacing the browser
    Web Speech API, which streams to the cloud). Ephemeral: nothing is persisted.
    Requires the Phoeniqs key; when unset the loader raises and we surface 503.
    """
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio file")

    filename = file.filename or "dictation.webm"
    content_type = file.content_type or "audio/webm"
    try:
        transcript = await transcribe_audio(
            data, filename=filename, content_type=content_type
        )
    except RuntimeError as exc:  # PHOENIQS_API_KEY unset
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # transport / model error
        log.warning("voice.dictation_failed", error=str(exc))
        raise HTTPException(status_code=502, detail=f"Transcription failed: {exc}") from exc

    log.info("voice.dictation", bytes=len(data), transcript_len=len(transcript))
    return DictationResponse(transcript=transcript)


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


class EventIn(BaseModel):
    title: str
    start: str               # local ISO-8601 datetime "YYYY-MM-DDTHH:MM:SS"
    end: str | None = None   # defaults to start + 1h
    notes: str | None = None


class CommitRequest(BaseModel):
    note: NoteIn
    dna_delta: DnaDelta = DnaDelta()
    audio_key: str | None = None     # MinIO key from /audio upload; None = no recording
    events: list[EventIn] = []       # approved follow-ups → calendar + email (Part B)


class CommitResponse(BaseModel):
    interaction_id: str
    dna_version: int | None
    audio_key: str | None
    events_created: int = 0          # calendar events written via Microsoft Graph


# ---------------------------------------------------------------------------
# /structure request / response models (TASK-047)
# ---------------------------------------------------------------------------


class StructureRequest(BaseModel):
    transcript: str
    today: str | None = None  # ISO date; falls back to server date.today()


class TaskProposalOut(BaseModel):
    title: str
    kind: str
    execution_mode: str  # "Auto" | "Manual"


class StructureResponse(BaseModel):
    note: NoteIn
    proposed_dna: list[dict]
    proposed_tasks: list[TaskProposalOut]
    proposed_events: list[dict] = []


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@router.post("/{client_id}/voice-notes/structure", response_model=StructureResponse)
async def structure_voice_note(
    client_id: uuid.UUID,
    body: StructureRequest,
    session: AsyncSession = Depends(get_session),
) -> StructureResponse:
    """Structure a raw transcript into a CRM note draft with DNA and task proposals.

    Pure LLM inference — never writes to the database (G1: RM must approve via /commit).
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    today_str = body.today or str(date.today())
    result: NoteStructureOutput = await structure_note(client.name, body.transcript, today_str)

    task_proposals_out: list[TaskProposalOut] = []
    for t in result.proposed_tasks:
        try:
            mode = classify_execution_mode(TaskKind(t.kind))
        except ValueError:
            mode = ExecutionMode.MANUAL
        task_proposals_out.append(
            TaskProposalOut(title=t.title, kind=t.kind, execution_mode=mode.value)
        )

    note_in = NoteIn(
        date=result.note.date,
        medium=result.note.medium,
        client_contact=result.note.client_contact,
        body=result.note.body,
    )

    log.info(
        "voice.structured",
        client_id=str(client_id),
        transcript_len=len(body.transcript),
        dna_proposals=len(result.proposed_dna),
        task_proposals=len(task_proposals_out),
    )

    return StructureResponse(
        note=note_in,
        proposed_dna=[d.model_dump() for d in result.proposed_dna],
        proposed_tasks=task_proposals_out,
        proposed_events=[e.model_dump() for e in result.proposed_events],
    )


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


class TranscribeResponse(BaseModel):
    transcript: str
    audio_key: str  # MinIO key for the stored recording; pass to /commit on approval


@router.post("/{client_id}/voice-notes/transcribe", response_model=TranscribeResponse)
async def transcribe_voice_note(
    client_id: uuid.UUID,
    file: UploadFile,
    session: AsyncSession = Depends(get_session),
) -> TranscribeResponse:
    """Store a recording and transcribe it to text via Whisper (TASK-047 capture).

    One call does two things so the RM records once:
    1. Persist the raw audio in MinIO (returns audio_key, linked on /commit).
    2. Transcribe via Whisper on Phoeniqs and return the raw text.

    Pure capture — never structures or writes a note (the RM reviews/edits the
    transcript, then calls /structure → /commit). Transcription requires the
    Phoeniqs key; when unset the loader raises and we surface 503 (no fallback).
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Empty audio file")

    filename = file.filename or "recording.webm"
    content_type = file.content_type or "audio/webm"
    key = f"voice-notes/{client_id}/{filename}"

    # put_object is synchronous (MinIO SDK) — offload to thread pool.
    await asyncio.to_thread(put_object, key, data, content_type)

    try:
        transcript = await transcribe_audio(
            data, filename=filename, content_type=content_type
        )
    except RuntimeError as exc:  # PHOENIQS_API_KEY unset
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:  # transport / model error
        log.warning("voice.transcribe_failed", client_id=str(client_id), error=str(exc))
        raise HTTPException(
            status_code=502, detail=f"Transcription failed: {exc}"
        ) from exc

    log.info(
        "voice.transcribed",
        client_id=str(client_id),
        key=key,
        bytes=len(data),
        transcript_len=len(transcript),
    )
    return TranscribeResponse(transcript=transcript, audio_key=key)


async def _save_events_to_calendar(client_name: str, events: list[EventIn]) -> int:
    """Create calendar events for approved follow-ups and email the RM a confirmation.

    RM-initiated (the RM committed the note), so within the autonomy boundary (G1).
    Best-effort: a Graph/sign-in failure is logged and skipped — it never fails the
    note commit, which is the durable record. Returns the number of events created.
    """
    if not settings.ms_graph_enabled:
        log.info("voice.calendar_skip", reason="MS_GRAPH_* unset")
        return 0

    mailbox = settings.ms_graph_mailbox
    created: list[str] = []
    for ev in events:
        try:
            end = ev.end or (
                datetime.fromisoformat(ev.start) + timedelta(hours=1)
            ).isoformat(timespec="seconds")
            await create_calendar_event(
                mailbox,
                ev.title,
                ev.start,
                end,
                body=ev.notes,
                timezone=settings.ms_graph_calendar_timezone,
            )
            created.append(f"{ev.start} — {ev.title}")
        except NotSignedInError:
            log.info("voice.calendar_skip", reason="RM not signed in")
            return 0
        except (ValueError, TypeError) as exc:
            log.warning("voice.calendar_bad_event", title=ev.title, start=ev.start, error=str(exc))
        except Exception as exc:  # noqa: BLE001 — never fail the commit on a Graph hiccup
            log.warning("voice.calendar_failed", title=ev.title, error=str(exc))

    # "Save on email also" — a single RM-facing confirmation of what was scheduled.
    if created:
        html = (
            f"<p>Scheduled from your note on <b>{client_name}</b>:</p><ul>"
            + "".join(f"<li>{c}</li>" for c in created)
            + "</ul>"
        )
        try:
            await send_via_graph(
                mailbox,
                settings.rm_email or mailbox,
                f"Scheduled: {len(created)} follow-up(s) — {client_name}",
                html,
                html=True,
            )
        except Exception as exc:  # noqa: BLE001 — confirmation is non-critical
            log.warning("voice.calendar_email_failed", error=str(exc))

    return len(created)


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

    # Part B: write approved follow-ups to the calendar + email the RM a confirmation.
    # Runs after the durable CRM write so a Graph hiccup never loses the note.
    events_created = await _save_events_to_calendar(client.name, body.events)

    log.info(
        "voice.commit",
        client_id=str(client_id),
        interaction_id=str(interaction.id),
        dna_version=dna_version,
        audio_key=body.audio_key,
        delta_keys=[k for k, v in delta_dict.items() if v],
        events_created=events_created,
    )

    return CommitResponse(
        interaction_id=str(interaction.id),
        dna_version=dna_version,
        audio_key=body.audio_key,
        events_created=events_created,
    )
