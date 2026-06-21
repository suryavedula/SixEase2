"""RM "My Topics" follow-list endpoints (Change Radar tabs).

The relationship manager curates a personal follow list; the Change Radar
"My Topics" tab filters the book-wide radar to the changes matching one of these.
Single-RM app — one global list, no user scoping. CRUD only: the actual
event↔follow matching happens client-side against the radar payload the widget
already holds (entity_key / entity_label), so there is one source of radar truth.

RM-only — a follow never touches a client (autonomy boundary G1).
"""

import re
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.logging import get_logger
from app.models.derived import RmFollow

router = APIRouter(prefix="/follows", tags=["follows"])
log = get_logger(__name__)


class FollowOut(BaseModel):
    id: str
    label: str
    keyword: str
    entity_key: str | None
    entity_type: str | None
    created_at: datetime


class FollowCreate(BaseModel):
    label: str
    keyword: str | None = None  # defaults to a normalised `label`
    entity_key: str | None = None
    entity_type: str | None = None


class FollowsResponse(BaseModel):
    follows: list[FollowOut]
    total: int


def _out(f: RmFollow) -> FollowOut:
    return FollowOut(
        id=str(f.id),
        label=f.label,
        keyword=f.keyword,
        entity_key=f.entity_key,
        entity_type=f.entity_type,
        created_at=f.created_at,
    )


def _norm_keyword(s: str) -> str:
    """Lowercase + collapse whitespace — the canonical dedup/match term."""
    return re.sub(r"\s+", " ", s or "").strip().lower()


@router.get("", response_model=FollowsResponse)
async def list_follows(session: AsyncSession = Depends(get_session)) -> FollowsResponse:
    """All "My Topics" follows, newest first."""
    rows = (
        await session.scalars(select(RmFollow).order_by(RmFollow.created_at.desc()))
    ).all()
    return FollowsResponse(follows=[_out(f) for f in rows], total=len(rows))


@router.post("", response_model=FollowOut, status_code=201)
async def create_follow(
    body: FollowCreate, session: AsyncSession = Depends(get_session)
) -> FollowOut:
    """Add a follow. Idempotent on `keyword` — re-adding the same topic returns
    the existing row (200-style) rather than erroring."""
    label = (body.label or "").strip()
    keyword = _norm_keyword(body.keyword or label)
    if not label or not keyword:
        raise HTTPException(status_code=422, detail="label (or keyword) is required")

    existing = await session.scalar(
        select(RmFollow).where(RmFollow.keyword == keyword)
    )
    if existing is not None:
        return _out(existing)

    follow = RmFollow(
        label=label,
        keyword=keyword,
        entity_key=body.entity_key,
        entity_type=body.entity_type,
    )
    session.add(follow)
    await session.commit()
    await session.refresh(follow)
    log.info("follows.create", keyword=keyword, entity_key=body.entity_key)
    return _out(follow)


@router.delete("/{follow_id}", status_code=204)
async def delete_follow(
    follow_id: uuid.UUID, session: AsyncSession = Depends(get_session)
) -> None:
    """Remove a follow. 404 if it does not exist (no silent no-op)."""
    result = await session.execute(delete(RmFollow).where(RmFollow.id == follow_id))
    if result.rowcount == 0:
        raise HTTPException(status_code=404, detail="follow not found")
    await session.commit()
    log.info("follows.delete", follow_id=str(follow_id))
