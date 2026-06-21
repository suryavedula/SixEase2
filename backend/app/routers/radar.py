"""Book-wide Change Radar read endpoint (TASK-059, EPIC-08).

Exposes the event-centric top-N across the whole book: each change ranked by
aggregate impact, carrying its impacted-client fan-out and a one-click fix per
client. The unit is the change/event, not the client.

Rows are materialised by POST /admin/seed/radar (loaders/change_radar.py).
Resolved events (client_count > 0) are returned ranked by impact_score DESC;
unresolved events (no entity / zero exposure) are surfaced separately so nothing
is silently dropped (no-fallbacks).
"""

import asyncio
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import radar_stream
from app.db import get_session
from app.logging import get_logger
from app.models.derived import ChangeEvent

router = APIRouter(prefix="/radar", tags=["radar"])
log = get_logger(__name__)


class ImpactedClient(BaseModel):
    client_id: str
    client_name: str
    exposure_chf: float | None
    exposure_pct: float | None
    drift_caused: float | None = None
    dna_note: str | None = None
    suggested_action: str | None = None
    alert_id: str | None = None
    swap_candidate: dict | None = None


class RadarEvent(BaseModel):
    id: str
    action: str | None
    entity_key: str | None
    entity_type: str | None
    entity_label: str | None
    source: str | None
    event_ts: datetime | None
    magnitude: float | None
    impact_score: float | None
    client_count: int
    total_exposure_chf: float | None
    impacted_clients: list[ImpactedClient]
    suggested_batch_action: str | None
    sources: list | None
    unresolved_reason: str | None = None
    news_url: str | None = None
    # Cross-source rank-normalized impact in [0,1] used for ordering (see get_radar).
    normalized_score: float | None = None


class RadarResponse(BaseModel):
    events: list[RadarEvent]
    unresolved: list[RadarEvent]
    total: int


def _to_event(row: ChangeEvent, normalized_score: float | None = None) -> RadarEvent:
    sources = row.sources or []
    news_url = next((s.get("url") for s in sources if isinstance(s, dict) and s.get("url")), None)
    return RadarEvent(
        id=str(row.id),
        action=row.action,
        entity_key=row.entity_key,
        entity_type=row.entity_type,
        entity_label=row.entity_label,
        source=row.source,
        event_ts=row.event_ts,
        magnitude=row.magnitude,
        impact_score=row.impact_score,
        client_count=row.client_count,
        total_exposure_chf=float(row.total_exposure_chf) if row.total_exposure_chf is not None else None,
        impacted_clients=[ImpactedClient(**c) for c in (row.impacted_clients or [])],
        suggested_batch_action=row.suggested_batch_action,
        sources=row.sources,
        unresolved_reason=row.unresolved_reason,
        news_url=news_url,
        normalized_score=normalized_score,
    )


def _rank_normalize_by_source(rows: list[ChangeEvent]) -> dict:
    """Rank-normalize impact_score to [0,1] WITHIN each source, keyed by row id.

    Drift events score in CHF millions while news events score in the hundreds of
    thousands — incomparable raw, so news is always outranked off the top-N. Ranking
    within each source (top item → 1.0, bottom → 0.0) puts a top news story on the
    same footing as a top drift breach, robust to the magnitude-scale gap and to
    outliers. Single-item sources map to 1.0.
    """
    from collections import defaultdict

    groups: dict[str, list[ChangeEvent]] = defaultdict(list)
    for r in rows:
        groups[r.source or ""].append(r)

    norm: dict = {}
    for items in groups.values():
        ordered = sorted(items, key=lambda r: (r.impact_score or 0.0), reverse=True)
        n = len(ordered)
        for i, r in enumerate(ordered):
            norm[r.id] = 1.0 if n == 1 else 1.0 - i / (n - 1)
    return norm


@router.get("/stream")
async def radar_stream_endpoint(request: Request) -> StreamingResponse:
    """Server-Sent Events stream of proactively-pushed changes (EPIC-08).

    The dispatch loop publishes each Critical change here; the browser's
    EventSource forwards it to the Action Center so new events surface live,
    without a manual refresh. A keepalive comment every 15 s holds the connection
    open and lets us detect client disconnects. RM-facing only.
    """

    async def event_gen():
        q = radar_stream.subscribe()
        try:
            yield ": connected\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    data = await asyncio.wait_for(q.get(), timeout=15)
                    yield f"data: {data}\n\n"
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
        finally:
            radar_stream.unsubscribe(q)

    return StreamingResponse(
        event_gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("", response_model=RadarResponse)
async def get_radar(
    limit: int = Query(default=10, ge=1, le=100),
    session: AsyncSession = Depends(get_session),
) -> RadarResponse:
    """Return the top-N book-wide changes ranked by cross-source normalized impact.

    Impact is rank-normalized WITHIN each source before merging (see
    _rank_normalize_by_source) so news competes fairly with CHF-drift breaches
    instead of being buried. Ties break on raw impact_score then recency, so the
    single biggest drift breach still leads while news fills the rest of the top-N.

    `events` holds resolved changes (client_count > 0, real exposure); `unresolved`
    holds entity-less or zero-exposure changes surfaced explicitly (no-fallbacks).
    """
    # Fetch ALL resolved events (not a SQL limit) so normalization sees every
    # source's full distribution; the top-N slice happens after re-ranking.
    resolved_stmt = (
        select(ChangeEvent)
        .where(ChangeEvent.client_count > 0, ChangeEvent.unresolved_reason.is_(None))
    )
    resolved_all = list((await session.scalars(resolved_stmt)).all())

    norm = _rank_normalize_by_source(resolved_all)
    resolved_all.sort(
        key=lambda r: (
            norm.get(r.id, 0.0),
            r.impact_score or 0.0,
            r.event_ts or datetime.min.replace(tzinfo=timezone.utc),
        ),
        reverse=True,
    )
    resolved = resolved_all[:limit]

    unresolved_stmt = (
        select(ChangeEvent)
        .where(ChangeEvent.unresolved_reason.isnot(None))
        .order_by(ChangeEvent.event_ts.desc().nullslast())
    )
    unresolved = (await session.scalars(unresolved_stmt)).all()

    log.info(
        "radar.read",
        resolved_total=len(resolved_all),
        returned=len(resolved),
        unresolved=len(unresolved),
        limit=limit,
    )

    return RadarResponse(
        events=[_to_event(r, norm.get(r.id)) for r in resolved],
        unresolved=[_to_event(r) for r in unresolved],
        total=len(resolved_all),
    )
