"""Holdings live-pricing enrichment (TASK-026, EPIC-06).

Resolves each held equity position to a SIX end-of-day price via the SIX MCP
client, writes live_price + live_price_at to enriched_holdings, and computes
positions.quantity. Bond positions (fixed-income SAC) use par-pricing instead of
live SIX data. Gracefully falls back when SIX is unavailable or returns no data.

Seeding order: seed/portfolio → seed/tags → seed/enrich
"""

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app import six
from app.logging import get_logger
from app.models.derived import EnrichedHolding
from app.models.source import Client, Position

log = get_logger(__name__)

_BOND_SAC = frozenset({
    "Domestic Bonds (CHF)",
    "Emerging Market Bonds",
    "Foreign Bonds (G7)",
})


async def enrich_holdings(
    session: AsyncSession,
    client_id: uuid.UUID | None = None,
    skip_synthetic: bool = True,
) -> dict[str, int]:
    """Fetch live EOD prices from SIX and write to enriched_holdings + positions.

    By default skips synthetic clients (names starting with "Synthetic") to avoid
    exhausting SIX rate limits across 100+ generated clients.

    Returns {"live_priced": N, "fallback_used": N, "quantity_set": N, "clients_processed": N}.
    """
    if client_id is not None:
        clients = (
            await session.execute(select(Client).where(Client.id == client_id))
        ).scalars().all()
    elif skip_synthetic:
        clients = (
            await session.execute(
                select(Client).where(~Client.name.like("Synthetic%"))
            )
        ).scalars().all()
    else:
        clients = (await session.execute(select(Client))).scalars().all()

    total_live = total_fallback = total_qty = 0

    for client in clients:
        n_live, n_fallback, n_qty = await _enrich_client(session, client)
        await session.commit()
        total_live += n_live
        total_fallback += n_fallback
        total_qty += n_qty
        log.info(
            "holdings.client_enriched",
            client=client.name,
            live=n_live,
            fallback=n_fallback,
            qty=n_qty,
        )

    log.info(
        "holdings.enrich_complete",
        clients=len(clients),
        live_priced=total_live,
        fallback_used=total_fallback,
        quantity_set=total_qty,
    )
    return {
        "live_priced": total_live,
        "fallback_used": total_fallback,
        "quantity_set": total_qty,
        "clients_processed": len(clients),
    }


async def _enrich_client(
    session: AsyncSession, client: Client
) -> tuple[int, int, int]:
    """Process all positions for one client. Returns (n_live, n_fallback, n_qty)."""
    positions = (
        await session.execute(select(Position).where(Position.client_id == client.id))
    ).scalars().all()

    n_live = n_fallback = n_qty = 0

    for position in positions:
        live_price, live_at = await _fetch_price(position)

        if live_price is not None:
            n_live += 1
        else:
            n_fallback += 1

        await session.execute(
            update(EnrichedHolding)
            .where(EnrichedHolding.position_id == position.id)
            .values(live_price=live_price, live_price_at=live_at)
        )

        quantity = _compute_quantity(position, live_price)
        if quantity is not None:
            await session.execute(
                update(Position)
                .where(Position.id == position.id)
                .values(quantity=quantity)
            )
            n_qty += 1

    return n_live, n_fallback, n_qty


async def _fetch_price(position: Position) -> tuple[float | None, datetime | None]:
    """Get EOD close price for a position. Returns (price, utc_timestamp) or (None, None)."""
    if position.sub_asset_class in _BOND_SAC:
        return None, None

    if not position.valor or not position.mic:
        log.warning(
            "holdings.no_listing_id",
            issuer=position.issuer,
            isin=position.isin,
            sub_asset_class=position.sub_asset_class,
        )
        return None, None

    listing_id = f"{position.valor}_{position.mic}"
    try:
        snapshot = await six.get_eod_snapshot(listing_id)
        live_at = datetime.now(tz=timezone.utc)
        if snapshot.timestamp:
            try:
                parsed = datetime.fromisoformat(snapshot.timestamp)
                live_at = parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
            except ValueError:
                pass
        return snapshot.close, live_at
    except Exception as exc:
        log.warning("holdings.six_failed", listing_id=listing_id, error=str(exc))
        return None, None


def _compute_quantity(position: Position, live_price: float | None) -> float | None:
    """Compute share/unit quantity for a position.

    Bonds: current_chf / 100 (face units — CLAUDE.md: qty = face ÷ 100; face = current_chf × 100).
    Equities: current_chf / live_price (approximate shares from workbook CHF ÷ live price).
    Returns None when computation is not possible.
    """
    current = float(position.current_chf) if position.current_chf is not None else None
    if current is None:
        return None

    if position.sub_asset_class in _BOND_SAC:
        return current / 100.0

    if live_price and live_price > 0:
        return current / live_price

    return None
