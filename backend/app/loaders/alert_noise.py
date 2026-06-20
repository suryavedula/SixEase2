"""Alert noise control (TASK-033, EPIC-08).

Four primitives that all alert generators (drift.py, alerts.py) call before
emitting an Alert row — realising §15 AL5 noise suppression:

  should_suppress(client_id, alert_class, dedup_key) -> bool   async
  record_cooldown(client_id, alert_class, dedup_key) -> None   async
  passes_threshold(value, threshold) -> bool                   pure
  build_needs_attention(session, client_id) -> dict            async

Cooldown state lives in Redis (24 h TTL keys) — no migration required.
Aggregation is a read-side GROUP BY on the existing alerts table.

Fail-open design: if Redis is unavailable, should_suppress returns False so
an infrastructure outage never silences alerts.
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models.derived import Alert
from app.models.enums import AlertStatus, Severity
from app.redis_client import cache_get, cache_set

log = get_logger(__name__)

_COOLDOWN_TTL: int = 86_400       # 24 hours
_COOLDOWN_PREFIX: str = "alert:cd"


def _make_cooldown_key(client_id: uuid.UUID, alert_class: str, dedup_key: str) -> str:
    return f"{_COOLDOWN_PREFIX}:{client_id}:{alert_class}:{dedup_key}"


async def should_suppress(
    client_id: uuid.UUID,
    alert_class: str,
    dedup_key: str,
) -> bool:
    """Return True if this alert should be dropped due to an active cooldown.

    Checks a Redis TTL key set by record_cooldown() after the previous emission.
    Fails open on Redis errors — an outage must never silence alerts.
    """
    try:
        hit = await cache_get(_make_cooldown_key(client_id, alert_class, dedup_key))
        if hit is not None:
            log.debug(
                "alert_noise.cooldown_suppressed",
                client_id=str(client_id),
                alert_class=alert_class,
                dedup_key=dedup_key,
            )
            return True
    except Exception as exc:
        log.warning(
            "alert_noise.redis_unavailable",
            error=str(exc),
            client_id=str(client_id),
            alert_class=alert_class,
        )
    return False


async def record_cooldown(
    client_id: uuid.UUID,
    alert_class: str,
    dedup_key: str,
) -> None:
    """Write a 24-hour Redis TTL key after an alert is emitted.

    Must be called AFTER session.commit() — a rolled-back alert must not
    leave a cooldown key that silences the next legitimate emission.
    """
    key = _make_cooldown_key(client_id, alert_class, dedup_key)
    try:
        await cache_set(key, {"fired": 1}, ttl=_COOLDOWN_TTL)
        log.debug(
            "alert_noise.cooldown_recorded",
            client_id=str(client_id),
            alert_class=alert_class,
            dedup_key=dedup_key,
        )
    except Exception as exc:
        log.warning("alert_noise.cooldown_write_failed", error=str(exc))


def passes_threshold(value: float, threshold: float) -> bool:
    """Return True when value strictly exceeds threshold (E12 gate).

    Pure function — import the domain constant at the call site:
        from app.loaders.swap import FIT_GAIN_THRESHOLD
        if not passes_threshold(fit_gain, FIT_GAIN_THRESHOLD): continue
    """
    return value > threshold


_FYI_LABELS: dict[str, str] = {
    "good_news": "good news item",
    "values_drift": "values-alignment note",
    "overdue_promise": "open promise",
    "quiet_client": "contact reminder",
    "behavioural_guardrail": "guardrail note",
}


def _fyi_label(alert_class: str | None, count: int) -> str:
    base = _FYI_LABELS.get(alert_class or "", alert_class or "alert")
    suffix = "s" if count != 1 else ""
    return f"{count} {base}{suffix}"


async def build_needs_attention(
    session: AsyncSession,
    client_id: uuid.UUID,
) -> dict:
    """Aggregate open alerts into a per-client summary card.

    Groups FYI alerts by alert_class; counts CRITICAL and ATTENTION separately.
    Returns a dict matching the NeedsAttentionResponse shape in routers/alerts.py.
    """
    rows = (
        await session.execute(
            select(
                Alert.alert_class,
                Alert.severity,
                func.count(Alert.id).label("cnt"),
            )
            .where(
                Alert.client_id == client_id,
                Alert.status == AlertStatus.OPEN,
            )
            .group_by(Alert.alert_class, Alert.severity)
        )
    ).all()

    critical = 0
    attention = 0
    fyi_groups: list[dict] = []
    total = 0

    for row in rows:
        cnt = int(row.cnt)
        total += cnt
        sev = row.severity.value if hasattr(row.severity, "value") else row.severity
        if sev == Severity.CRITICAL.value:
            critical += cnt
        elif sev == Severity.ATTENTION.value:
            attention += cnt
        else:
            fyi_groups.append({
                "alert_class": row.alert_class,
                "count": cnt,
                "label": _fyi_label(row.alert_class, cnt),
            })

    log.debug(
        "alert_noise.needs_attention_built",
        client_id=str(client_id),
        critical=critical,
        attention=attention,
        fyi_groups=len(fyi_groups),
        total=total,
    )

    return {
        "client_id": str(client_id),
        "critical_count": critical,
        "attention_count": attention,
        "fyi_groups": sorted(fyi_groups, key=lambda g: -g["count"]),
        "total_open": total,
    }
