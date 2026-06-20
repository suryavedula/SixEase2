"""Alert prioritisation scoring (TASK-034, EPIC-08).

Computes and persists rank_score for every open alert.
Formula: severity_base × class_weight × confidence × emotional_multiplier

- severity_base: CRITICAL=3.0, ATTENTION=2.0, FYI=1.0
- class_weight: ordered by operational urgency (dna_conflict highest, good_news lowest)
- confidence: already stored on each Alert (0.0–1.0)
- emotional_multiplier: 1.3× on REACH_OUT / panic / quiet_client / good_news alerts
  for clients whose DNA temperament contains anxiety-related keywords (AL6 / UC-24)

Not AUM-based. Idempotent: safe to re-run after any seed/alerts or seed/drift pass.
Seeding order: seed/alerts + seed/drift → seed/rank
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models.derived import Alert, ClientDNA
from app.models.source import Client

log = get_logger(__name__)

_SEVERITY_BASE: dict[str, float] = {
    "CRITICAL": 3.0,
    "ATTENTION": 2.0,
    "FYI": 1.0,
}

_CLASS_WEIGHT: dict[str, float] = {
    "dna_conflict":          1.00,
    "panic":                 0.95,
    "quiet_client":          0.90,
    "drift_breach":          0.85,
    "news_impact":           0.80,
    "overdue_promise":       0.75,
    "stale_sell":            0.70,
    "behavioural_guardrail": 0.60,
    "values_drift":          0.50,
    "good_news":             0.40,
}

_EMOTIONAL_KEYWORDS: frozenset[str] = frozenset({
    "anxious", "anxiety", "worried", "reactive", "emotional",
    "nervous", "impulsive", "fearful", "panic",
})

_EMOTIONAL_CLASSES: frozenset[str] = frozenset({
    "panic", "quiet_client", "good_news",
})


def _emotional_multiplier(temperament: str | None, alert: Alert) -> float:
    if not temperament:
        return 1.0
    t = temperament.lower()
    if not any(kw in t for kw in _EMOTIONAL_KEYWORDS):
        return 1.0
    action = alert.action_type.value if hasattr(alert.action_type, "value") else str(alert.action_type)
    if action == "REACH_OUT" or (alert.alert_class or "") in _EMOTIONAL_CLASSES:
        return 1.3
    return 1.0


def compute_rank_score(alert: Alert, temperament: str | None) -> float:
    """Return the AL6 priority score for one alert.

    Pure function — no DB access. Used by rank_alerts() and testable in isolation.
    """
    sev = alert.severity.value if hasattr(alert.severity, "value") else str(alert.severity)
    base = _SEVERITY_BASE.get(sev, 1.0)
    cw = _CLASS_WEIGHT.get(alert.alert_class or "", 0.5)
    conf = alert.confidence if alert.confidence is not None else 0.5
    emo = _emotional_multiplier(temperament, alert)
    return base * cw * conf * emo


async def rank_alerts(
    session: AsyncSession,
    client_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Compute and persist rank_score for all open alerts (or one client's).

    Fetches each client's DNA temperament, scores every alert, writes rank_score
    back in-place, and commits once per client. Returns totals.
    """
    if client_id is not None:
        clients = (
            await session.execute(select(Client).where(Client.id == client_id))
        ).scalars().all()
    else:
        clients = (await session.execute(select(Client))).scalars().all()

    total_ranked = 0

    for client in clients:
        dna = await session.scalar(
            select(ClientDNA).where(ClientDNA.client_id == client.id)
        )
        temperament = dna.temperament if dna is not None else None

        alerts = (
            await session.execute(
                select(Alert).where(Alert.client_id == client.id)
            )
        ).scalars().all()

        for alert in alerts:
            alert.rank_score = compute_rank_score(alert, temperament)

        await session.commit()
        total_ranked += len(alerts)
        log.info("rank.client_scored", client=client.name, alerts=len(alerts))

    log.info("rank.complete", clients_processed=len(clients), alerts_ranked=total_ranked)
    return {"clients_processed": len(clients), "alerts_ranked": total_ranked}
