"""Alert and news read/update endpoints (TASK-022 / TASK-028 / TASK-034 / TASK-035, EPIC-05 / EPIC-06 / EPIC-08).

Exposes the per-client alert queue and matched news items.
Alerts are ordered by rank_score DESC (AL6 prioritisation, TASK-034); news items by recency.

Alerts are written by POST /admin/seed/drift and POST /admin/seed/alerts.
rank_score is written by POST /admin/seed/rank (TASK-034).
News items are written by POST /admin/scan/news.
Lifecycle transitions (act/dismiss/snooze/convert-to-task) via PATCH + POST /convert (TASK-035).
"""

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.logging import get_logger
from app.models.derived import Alert, NewsItem, Task
from app.models.enums import AlertStatus, ExecutionMode, TaskStatus
from app.models.source import Client

router = APIRouter(prefix="/clients", tags=["alerts"])
log = get_logger(__name__)


class AlertItem(BaseModel):
    id: str
    alert_class: str | None
    action_type: str
    severity: str
    trigger: str | None
    why: str | None
    suggested_action: str | None
    status: str
    confidence: float | None
    rank_score: float | None
    evidence: list | None
    created_at: datetime
    snoozed_until: datetime | None = None
    dismissed_reason: str | None = None


class AlertsResponse(BaseModel):
    client_id: str
    client_name: str
    alerts: list[AlertItem]
    total: int


@router.get("/{client_id}/alerts", response_model=AlertsResponse)
async def get_client_alerts(
    client_id: uuid.UUID,
    status: str | None = Query(default=None, description="Filter by status (open, acted, dismissed, snoozed, converted)"),
    alert_class: str | None = Query(default=None, description="Filter by class (drift_breach, stale_sell, ...)"),
    session: AsyncSession = Depends(get_session),
) -> AlertsResponse:
    """Return the alert queue for a client, ordered by rank_score DESC (AL6, TASK-034)."""
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    stmt = (
        select(Alert)
        .where(Alert.client_id == client_id)
        .order_by(Alert.rank_score.desc().nullslast(), Alert.created_at.desc())
    )
    if status is not None:
        stmt = stmt.where(Alert.status == status)
    if alert_class is not None:
        stmt = stmt.where(Alert.alert_class == alert_class)

    rows = (await session.execute(stmt)).scalars().all()

    alerts = [
        AlertItem(
            id=str(a.id),
            alert_class=a.alert_class,
            action_type=a.action_type.value if hasattr(a.action_type, "value") else a.action_type,
            severity=a.severity.value if hasattr(a.severity, "value") else a.severity,
            trigger=a.trigger,
            why=a.why,
            suggested_action=a.suggested_action,
            status=a.status.value if hasattr(a.status, "value") else a.status,
            confidence=a.confidence,
            rank_score=a.rank_score,
            evidence=a.evidence,
            created_at=a.created_at,
            snoozed_until=a.snoozed_until,
            dismissed_reason=a.dismissed_reason,
        )
        for a in rows
    ]

    log.info(
        "alerts.read",
        client_id=str(client_id),
        client_name=client.name,
        total=len(alerts),
        status_filter=status,
        class_filter=alert_class,
    )

    return AlertsResponse(
        client_id=str(client_id),
        client_name=client.name,
        alerts=alerts,
        total=len(alerts),
    )


class FYIGroup(BaseModel):
    alert_class: str | None
    count: int
    label: str


class NeedsAttentionResponse(BaseModel):
    client_id: str
    client_name: str
    critical_count: int
    attention_count: int
    fyi_groups: list[FYIGroup]
    total_open: int


@router.get("/{client_id}/needs-attention", response_model=NeedsAttentionResponse)
async def get_needs_attention(
    client_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> NeedsAttentionResponse:
    """Aggregated alert summary for the RM dashboard badge and needs-attention card.

    Groups open FYI alerts by class into rollup cards; returns separate counts
    for CRITICAL and ATTENTION bands. Use GET /clients/{id}/alerts for the full list.
    """
    from app.loaders.alert_noise import build_needs_attention

    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    summary = await build_needs_attention(session, client_id)

    log.info(
        "alerts.needs_attention",
        client_id=str(client_id),
        client_name=client.name,
        critical=summary["critical_count"],
        attention=summary["attention_count"],
        fyi_groups=len(summary["fyi_groups"]),
        total_open=summary["total_open"],
    )

    return NeedsAttentionResponse(
        client_id=str(client_id),
        client_name=client.name,
        critical_count=summary["critical_count"],
        attention_count=summary["attention_count"],
        fyi_groups=[FYIGroup(**g) for g in summary["fyi_groups"]],
        total_open=summary["total_open"],
    )


class NewsItemOut(BaseModel):
    id: str
    headline: str | None
    source: str | None
    url: str | None
    published_at: datetime | None
    sentiment: float | None
    matched_holdings: list | None
    matched_themes: list | None
    impact: str | None
    is_seeded: bool


class NewsResponse(BaseModel):
    client_id: str
    client_name: str
    items: list[NewsItemOut]
    total: int


@router.get("/{client_id}/news", response_model=NewsResponse)
async def get_client_news(
    client_id: uuid.UUID,
    limit: int = Query(default=20, le=100),
    impact: str | None = Query(default=None, description="Filter by impact: threat, opportunity, moment"),
    session: AsyncSession = Depends(get_session),
) -> NewsResponse:
    """Return matched news items for a client, ordered by recency (TASK-028)."""
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    stmt = (
        select(NewsItem)
        .where(NewsItem.client_ids.contains([str(client_id)]))
        .order_by(NewsItem.published_at.desc().nullslast())
        .limit(limit)
    )
    if impact is not None:
        stmt = stmt.where(NewsItem.impact == impact)

    rows = (await session.scalars(stmt)).all()

    items = [
        NewsItemOut(
            id=str(r.id),
            headline=r.headline,
            source=r.source,
            url=r.url,
            published_at=r.published_at,
            sentiment=r.sentiment,
            matched_holdings=r.matched_holdings,
            matched_themes=r.matched_themes,
            impact=r.impact,
            is_seeded=r.is_seeded,
        )
        for r in rows
    ]

    log.info(
        "news.read",
        client_id=str(client_id),
        client_name=client.name,
        total=len(items),
        impact_filter=impact,
    )

    return NewsResponse(
        client_id=str(client_id),
        client_name=client.name,
        items=items,
        total=len(items),
    )


# ---------------------------------------------------------------------------
# TASK-035 — Alert lifecycle write endpoints (AL7 / UC-26)
# ---------------------------------------------------------------------------

_VALID_PATCH_STATUSES = frozenset({"acted", "dismissed", "snoozed"})


class AlertTransitionRequest(BaseModel):
    status: str
    snoozed_until: datetime | None = None
    dismissed_reason: str | None = None

    @model_validator(mode="after")
    def _validate(self) -> "AlertTransitionRequest":
        if self.status not in _VALID_PATCH_STATUSES:
            raise ValueError(
                f"status must be one of {sorted(_VALID_PATCH_STATUSES)}; "
                "use POST /convert to set converted"
            )
        if self.status == "snoozed" and self.snoozed_until is None:
            raise ValueError("snoozed_until is required when status is 'snoozed'")
        if self.status != "snoozed" and self.snoozed_until is not None:
            raise ValueError("snoozed_until is only valid when status is 'snoozed'")
        if self.status != "dismissed" and self.dismissed_reason is not None:
            raise ValueError("dismissed_reason is only valid when status is 'dismissed'")
        return self


@router.patch("/{client_id}/alerts/{alert_id}", response_model=AlertItem)
async def transition_alert(
    client_id: uuid.UUID,
    alert_id: uuid.UUID,
    body: AlertTransitionRequest,
    session: AsyncSession = Depends(get_session),
) -> AlertItem:
    """Transition an alert through its lifecycle (AL7 / TASK-035).

    Allowed status values: acted | dismissed | snoozed
    Use POST /convert to set the converted status.
    dismissed_reason is persisted as a calibration signal (UC-26).
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    alert = await session.get(Alert, alert_id)
    if alert is None or alert.client_id != client_id:
        raise HTTPException(status_code=404, detail="Alert not found")

    status_map = {s.value: s for s in AlertStatus}
    new_status = status_map.get(body.status)
    if new_status is None:
        raise HTTPException(status_code=422, detail=f"Unknown status: {body.status}")

    alert.status = new_status
    alert.snoozed_until = body.snoozed_until
    alert.dismissed_reason = body.dismissed_reason
    await session.commit()

    log.info(
        "alert.transition",
        alert_id=str(alert_id),
        client_id=str(client_id),
        new_status=body.status,
        dismissed_reason=body.dismissed_reason,
    )

    return AlertItem(
        id=str(alert.id),
        alert_class=alert.alert_class,
        action_type=alert.action_type.value if hasattr(alert.action_type, "value") else alert.action_type,
        severity=alert.severity.value if hasattr(alert.severity, "value") else alert.severity,
        trigger=alert.trigger,
        why=alert.why,
        suggested_action=alert.suggested_action,
        status=alert.status.value if hasattr(alert.status, "value") else alert.status,
        confidence=alert.confidence,
        rank_score=alert.rank_score,
        evidence=alert.evidence,
        created_at=alert.created_at,
        snoozed_until=alert.snoozed_until,
        dismissed_reason=alert.dismissed_reason,
    )


class ConvertResponse(BaseModel):
    alert_id: str
    task_id: str


@router.post("/{client_id}/alerts/{alert_id}/convert", response_model=ConvertResponse)
async def convert_alert_to_task(
    client_id: uuid.UUID,
    alert_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> ConvertResponse:
    """Convert an alert into a Task and mark it as converted (AL7 / TASK-035).

    Creates a Task row with source="alert", execution_mode=MANUAL, status=CREATED.
    Returns both the alert_id and the new task_id.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    alert = await session.get(Alert, alert_id)
    if alert is None or alert.client_id != client_id:
        raise HTTPException(status_code=404, detail="Alert not found")

    if alert.status == AlertStatus.CONVERTED:
        raise HTTPException(status_code=409, detail="Alert already converted to a task")

    task = Task(
        client_id=client.id,
        alert_id=alert.id,
        source="alert",
        execution_mode=ExecutionMode.MANUAL,
        status=TaskStatus.CREATED,
        title=alert.trigger or alert.alert_class or "Alert task",
    )
    session.add(task)
    alert.status = AlertStatus.CONVERTED
    await session.commit()
    await session.refresh(task)

    log.info(
        "alert.converted_to_task",
        alert_id=str(alert_id),
        task_id=str(task.id),
        client_id=str(client_id),
    )

    return ConvertResponse(alert_id=str(alert.id), task_id=str(task.id))
