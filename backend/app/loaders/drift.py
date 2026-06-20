"""Drift breach and stale-SELL detection (TASK-022, EPIC-05).

Reads positions + mandate_strategies to detect sub-asset-class drift per client
(E10: ±2.0pp threshold), and positions × cio_recommendations to find held SELL-rated
instruments. Writes Alert rows for both types.

Idempotent: deletes drift_breach and stale_sell alerts per client before re-creating.
Commits once per client so a failure on client N does not roll back N-1.

Seeding order: seed/portfolio → seed/drift (no DNA or fit dependency)
"""

import uuid
from collections import defaultdict
from datetime import date

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.loaders.alert_noise import record_cooldown, should_suppress
from app.logging import get_logger
from app.models.derived import Alert
from app.models.enums import ActionType, AlertStatus, CIORating, Severity
from app.models.source import CIORecommendation, Client, MandateStrategy, Position

log = get_logger(__name__)

DRIFT_THRESHOLD_PP: float = 2.0  # E10 — ±2.0 percentage points
DRIFT_CRITICAL_PP: float = 5.0   # escalate to CRITICAL above this magnitude
SELL_CRITICAL_DAYS: int = 90     # stale SELL held > 90 days → CRITICAL

_DRIFT_CLASS = "drift_breach"
_SELL_CLASS = "stale_sell"


async def compute_drift(
    session: AsyncSession,
    client_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Detect drift breaches and stale SELLs for all clients (or one).

    Returns {"clients_processed": N, "drift_breach": N, "stale_sell": N}.
    """
    if client_id is not None:
        clients = (
            await session.execute(select(Client).where(Client.id == client_id))
        ).scalars().all()
    else:
        clients = (await session.execute(select(Client))).scalars().all()

    # Fetch all SELL rows once — used by every client
    sell_rows = (
        await session.execute(
            select(CIORecommendation).where(CIORecommendation.rating == CIORating.SELL)
        )
    ).scalars().all()
    sell_by_isin: dict[str, CIORecommendation] = {
        row.isin: row for row in sell_rows if row.isin
    }

    total_drift = 0
    total_sell = 0

    for client in clients:
        # Idempotency: wipe this client's auto-generated alerts before recomputing
        await session.execute(
            delete(Alert).where(
                Alert.client_id == client.id,
                Alert.alert_class.in_([_DRIFT_CLASS, _SELL_CLASS]),
            )
        )

        emitted_keys: list[tuple[str, str]] = []

        n_drift = await _detect_drift_breaches(session, client, emitted_keys)
        n_sell = await _detect_stale_sells(session, client, sell_by_isin, emitted_keys)

        await session.commit()

        for cls, key in emitted_keys:
            await record_cooldown(client.id, cls, key)

        total_drift += n_drift
        total_sell += n_sell
        log.info(
            "drift.client_processed",
            client=client.name,
            drift_breach=n_drift,
            stale_sell=n_sell,
        )

    log.info(
        "drift.compute_complete",
        clients=len(clients),
        drift_breach=total_drift,
        stale_sell=total_sell,
    )
    return {
        "clients_processed": len(clients),
        "drift_breach": total_drift,
        "stale_sell": total_sell,
    }


async def _detect_drift_breaches(
    session: AsyncSession,
    client: Client,
    emitted_keys: list[tuple[str, str]],
) -> int:
    """Compute sub-asset-class drift for client and emit breach alerts."""
    positions = (
        await session.execute(
            select(Position).where(
                Position.client_id == client.id,
                Position.current_chf.isnot(None),
            )
        )
    ).scalars().all()

    if not positions:
        return 0

    total_chf = sum(float(p.current_chf) for p in positions)
    if total_chf == 0:
        return 0

    sac_chf: dict[str, float] = defaultdict(float)
    for p in positions:
        if p.sub_asset_class:
            sac_chf[p.sub_asset_class] += float(p.current_chf)

    strategies = (
        await session.execute(
            select(MandateStrategy).where(MandateStrategy.mandate == client.mandate)
        )
    ).scalars().all()

    count = 0
    for strategy in strategies:
        sac = strategy.sub_asset_class
        current_pp = (sac_chf.get(sac, 0.0) / total_chf) * 100
        target_pp = float(strategy.target_weight)  # stored as percentage (Numeric 5,2)
        drift_pp = current_pp - target_pp

        if abs(drift_pp) <= DRIFT_THRESHOLD_PP:
            continue

        dedup_key = sac
        if await should_suppress(client.id, _DRIFT_CLASS, dedup_key):
            continue

        severity = Severity.CRITICAL if abs(drift_pp) > DRIFT_CRITICAL_PP else Severity.ATTENTION
        session.add(
            Alert(
                client_id=client.id,
                alert_class=_DRIFT_CLASS,
                action_type=ActionType.TRADE,
                severity=severity,
                status=AlertStatus.OPEN,
                trigger=f"{sac}: {drift_pp:+.2f}pp (current {current_pp:.2f}%, target {target_pp:.2f}%)",
                why="Sub-asset-class weight is outside the ±2.0pp mandate band (E10)",
                suggested_action="Rebalance sub-asset class to restore mandate weights",
                confidence=1.0,
                evidence=[{
                    "sub_asset_class": sac,
                    "drift_pp": round(drift_pp, 4),
                    "current_pp": round(current_pp, 4),
                    "target_pp": target_pp,
                    "total_chf": round(total_chf, 2),
                }],
            )
        )
        emitted_keys.append((_DRIFT_CLASS, dedup_key))
        count += 1

    return count


async def _detect_stale_sells(
    session: AsyncSession,
    client: Client,
    sell_by_isin: dict[str, CIORecommendation],
    emitted_keys: list[tuple[str, str]],
) -> int:
    """Flag held positions whose ISIN appears in the CIO SELL list."""
    if not sell_by_isin:
        return 0

    positions = (
        await session.execute(
            select(Position).where(
                Position.client_id == client.id,
                Position.isin.isnot(None),
            )
        )
    ).scalars().all()

    count = 0
    today = date.today()

    for position in positions:
        cio_row = sell_by_isin.get(position.isin)
        if cio_row is None:
            continue

        dedup_key = position.isin
        if await should_suppress(client.id, _SELL_CLASS, dedup_key):
            continue

        age_days: int | None = None
        if cio_row.rating_since:
            age_days = (today - cio_row.rating_since).days

        severity = (
            Severity.CRITICAL
            if age_days is not None and age_days > SELL_CRITICAL_DAYS
            else Severity.ATTENTION
        )

        age_str = f"{age_days}d" if age_days is not None else "unknown age"
        session.add(
            Alert(
                client_id=client.id,
                alert_class=_SELL_CLASS,
                action_type=ActionType.TRADE,
                severity=severity,
                status=AlertStatus.OPEN,
                trigger=f"{position.issuer or position.isin} — CIO SELL since {cio_row.rating_since} ({age_str})",
                why="Holding a CIO-rated SELL instrument; position should be reviewed for disposal",
                suggested_action="Review for disposal or swap to a BUY-rated same-sector replacement",
                confidence=1.0,
                evidence=[{
                    "isin": position.isin,
                    "issuer": position.issuer,
                    "security": position.security,
                    "rating_since": str(cio_row.rating_since) if cio_row.rating_since else None,
                    "age_days": age_days,
                    "cio_view": cio_row.cio_view,
                    "current_chf": float(position.current_chf) if position.current_chf else None,
                }],
            )
        )
        emitted_keys.append((_SELL_CLASS, dedup_key))
        count += 1

    return count
