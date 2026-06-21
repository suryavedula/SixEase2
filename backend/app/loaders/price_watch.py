"""SIX price-watch — the free (non-token-metered) proactive signal axis (EPIC-08).

SIX market data is JSON-RPC, not token-billed, so this scan can run continuously
without touching the hosted-LLM (Phoeniqs) budget. It emits Alert rows exactly
like drift/news do — `price_move` for an instrument that moved beyond a threshold,
`maturity_soon` for a bond approaching maturity — and `build_change_radar` then
fans them out by exposure into `change_events`, which the dispatch loop pushes to
the RM. No new aggregation path: it reuses the existing radar pipeline end-to-end.

Read-only sensing surfaced to the RM (autonomy boundary G1) — never an action.
No-fallbacks: a listing SIX can't price is logged and skipped, never invented.

Usage (from main.py lifespan via price_refresh.py):
    counts = await scan_price_signals(session)
"""

import asyncio
import uuid
from datetime import date, datetime

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app import six
from app.config import get_settings
from app.loaders.alert_noise import record_cooldown, should_suppress
from app.logging import get_logger
from app.models.derived import Alert
from app.models.enums import ActionType, AlertStatus, Severity
from app.models.source import Client, Position
from app.redis_client import cache_get, cache_set

log = get_logger(__name__)
settings = get_settings()

_PRICE_CLASS = "price_move"
_MATURITY_CLASS = "maturity_soon"

# Bonds are par-priced (no live equity snapshot) — they take the maturity path.
_BOND_SAC = frozenset({
    "Domestic Bonds (CHF)",
    "Emerging Market Bonds",
    "Foreign Bonds (G7)",
})

# Last observed close per listing — baseline for the next cycle's move (no TTL
# expiry needed; refreshed every scan). Stored via the JSON cache helpers.
_LASTCLOSE_PREFIX = "six:lastclose"


def _lastclose_key(listing_id: str) -> str:
    return f"{_LASTCLOSE_PREFIX}:{listing_id}"


async def scan_price_signals(session: AsyncSession) -> dict[str, int]:
    """Scan held instruments via SIX and emit price-move / maturity Alert rows.

    Idempotent per client (mirrors drift.py): wipes this client's open
    price_move/maturity_soon alerts, then re-creates them from the current scan.
    Respects RM dismissals via the 24 h cooldown (alert_noise). Skips synthetic
    clients to stay inside SIX rate limits.

    Returns {"clients_processed", "price_move", "maturity_soon", "priced", "skipped"}.
    """
    clients = (
        await session.execute(select(Client).where(~Client.name.like("Synthetic%")))
    ).scalars().all()

    today = date.today()
    total_price = total_maturity = total_priced = total_skipped = 0

    for client in clients:
        await session.execute(
            delete(Alert).where(
                Alert.client_id == client.id,
                Alert.alert_class.in_([_PRICE_CLASS, _MATURITY_CLASS]),
                Alert.status == AlertStatus.OPEN,
            )
        )

        positions = (
            await session.execute(select(Position).where(Position.client_id == client.id))
        ).scalars().all()

        emitted_keys: list[tuple[str, str]] = []
        n_price = n_maturity = n_priced = n_skipped = 0

        for position in positions:
            if position.sub_asset_class in _BOND_SAC:
                made, ok = await _check_maturity(session, client, position, today, emitted_keys)
                n_maturity += made
                n_skipped += 0 if ok else 1
            else:
                made, priced = await _check_price_move(session, client, position, emitted_keys)
                n_price += made
                n_priced += 1 if priced else 0
                n_skipped += 0 if priced else 1
            # Throttle: SIX caps at 5 req/s per cert. Each position makes one SIX
            # call, so pace the sequential loop to stay safely under the limit.
            if settings.price_watch_throttle_s > 0:
                await asyncio.sleep(settings.price_watch_throttle_s)

        await session.commit()
        for cls, key in emitted_keys:
            await record_cooldown(client.id, cls, key)

        total_price += n_price
        total_maturity += n_maturity
        total_priced += n_priced
        total_skipped += n_skipped
        log.info(
            "price_watch.client_processed",
            client=client.name, price_move=n_price, maturity_soon=n_maturity,
            priced=n_priced, skipped=n_skipped,
        )

    log.info(
        "price_watch.scan_complete",
        clients=len(clients), price_move=total_price, maturity_soon=total_maturity,
        priced=total_priced, skipped=total_skipped,
    )
    return {
        "clients_processed": len(clients),
        "price_move": total_price,
        "maturity_soon": total_maturity,
        "priced": total_priced,
        "skipped": total_skipped,
    }


async def _check_price_move(
    session: AsyncSession,
    client: Client,
    position: Position,
    emitted_keys: list[tuple[str, str]],
) -> tuple[int, bool]:
    """Emit a price_move alert if the position moved beyond the threshold.

    Returns (alerts_made, priced_ok). Move is measured against the last observed
    close (multi-cycle / overnight) when a baseline exists, else against the
    session open from the same snapshot — both are real SIX-sourced moves, never
    fabricated. The baseline is refreshed every scan.
    """
    if not position.valor or not position.mic:
        return 0, False

    listing_id = f"{position.valor}_{position.mic}"
    try:
        snap = await six.get_eod_snapshot(listing_id)
    except Exception as exc:
        log.warning("price_watch.six_failed", listing_id=listing_id, error=str(exc))
        return 0, False

    cached = await cache_get(_lastclose_key(listing_id))
    prev_close = cached.get("close") if cached else None
    baseline = prev_close if (prev_close and prev_close > 0) else snap.open
    basis = "prev_close" if (prev_close and prev_close > 0) else "session_open"

    # Always refresh the baseline for the next cycle.
    await cache_set(_lastclose_key(listing_id), {"close": snap.close, "ts": snap.timestamp})

    if not baseline or baseline <= 0:
        return 0, True  # priced, but no comparison basis yet (no-fallbacks)

    pct = (snap.close - baseline) / baseline * 100.0
    if abs(pct) < settings.price_move_threshold_pct:
        return 0, True

    if not position.isin:
        return 0, True  # can't fan out by exposure without an ISIN; surfaced via skip count
    if await should_suppress(client.id, _PRICE_CLASS, position.isin):
        return 0, True

    severity = (
        Severity.CRITICAL
        if abs(pct) >= settings.price_move_critical_pct
        else Severity.ATTENTION
    )
    direction = "up" if pct > 0 else "down"
    label = position.issuer or position.security or position.isin
    session.add(
        Alert(
            client_id=client.id,
            alert_class=_PRICE_CLASS,
            action_type=ActionType.WATCH,
            severity=severity,
            status=AlertStatus.OPEN,
            trigger=f"{label} {direction} {pct:+.1f}% to {snap.close:.2f} {snap.currency} (vs {basis})",
            why="A held position moved sharply — review for client impact or a proactive reach-out",
            suggested_action="Review the move; consider a reassuring or opportunity note to exposed clients",
            confidence=1.0,
            evidence=[{
                "isin": position.isin,
                "issuer": position.issuer,
                "security": position.security,
                "listing_id": listing_id,
                "close": snap.close,
                "baseline": round(baseline, 4),
                "basis": basis,
                "move_pct": round(pct, 2),
                "currency": snap.currency,
                "as_of": snap.timestamp,
                "source": "six.end_of_day_snapshot",
            }],
        )
    )
    emitted_keys.append((_PRICE_CLASS, position.isin))
    return 1, True


async def _check_maturity(
    session: AsyncSession,
    client: Client,
    position: Position,
    today: date,
    emitted_keys: list[tuple[str, str]],
) -> tuple[int, bool]:
    """Emit a maturity_soon alert if a bond matures within the horizon.

    Returns (alerts_made, resolved_ok). resolved_ok is False when SIX could not
    return maturity terms (logged + skipped, never invented)."""
    if not position.valor:
        return 0, False

    try:
        terms = await six.get_bond_terms(position.valor)
    except Exception as exc:
        log.warning("price_watch.maturity_lookup_failed", valor=position.valor, error=str(exc))
        return 0, False

    try:
        maturity = datetime.fromisoformat(terms.maturity_date).date()
    except (ValueError, TypeError):
        log.warning("price_watch.bad_maturity_date", valor=position.valor, raw=terms.maturity_date)
        return 0, False

    days_to = (maturity - today).days
    if days_to < 0 or days_to > settings.bond_maturity_horizon_days:
        return 0, True

    isin = position.isin or terms.isin
    if not isin:
        return 0, True
    if await should_suppress(client.id, _MATURITY_CLASS, isin):
        return 0, True

    severity = Severity.CRITICAL if days_to <= 7 else Severity.ATTENTION
    label = position.issuer or position.security or isin
    session.add(
        Alert(
            client_id=client.id,
            alert_class=_MATURITY_CLASS,
            action_type=ActionType.REACH_OUT,
            severity=severity,
            status=AlertStatus.OPEN,
            trigger=f"{label} matures in {days_to}d ({maturity.isoformat()})",
            why="A bond is maturing — the redemption proceeds need a reinvestment decision",
            suggested_action="Plan reinvestment; draft a note to the client about the maturing position",
            confidence=1.0,
            evidence=[{
                "isin": isin,
                "issuer": position.issuer,
                "security": position.security,
                "valor": position.valor,
                "maturity_date": maturity.isoformat(),
                "days_to_maturity": days_to,
                "coupon_rate": terms.coupon_rate,
                "currency": terms.currency,
                "source": "six.instrument_base",
            }],
        )
    )
    emitted_keys.append((_MATURITY_CLASS, isin))
    return 1, True
