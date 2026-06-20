"""Per-client watchlist builder (TASK-027, EPIC-06).

Derives, per client, a watchlist = held entities (issuer/ticker/ISIN from
positions) UNION DNA themes (tag tokens from client_dna.exclusions/tilts/values).
Stores the result in client_watchlists (one row per client, idempotent upsert).

Also exposes get_global_index() — the union of all clients' keywords — which
TASK-029's sequential poller uses as the single Event Registry feed filter (§14.2 F1).

Seeding order: seed/portfolio → seed/dna → seed/watchlist
"""

import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models.derived import ClientDNA, ClientWatchlist
from app.models.source import Client, Position

log = get_logger(__name__)


async def build_watchlists(
    session: AsyncSession,
    client_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Build (or rebuild) watchlist rows for all clients (or one if client_id given).

    Commits once per client so a failure on client N does not roll back N-1.
    Returns {client_name: 1} for each successfully processed client.
    """
    if client_id is not None:
        clients = (
            await session.execute(select(Client).where(Client.id == client_id))
        ).scalars().all()
    else:
        clients = (await session.execute(select(Client))).scalars().all()

    results: dict[str, int] = {}

    for client in clients:
        dna = await session.scalar(
            select(ClientDNA).where(ClientDNA.client_id == client.id)
        )
        if dna is None:
            if client_id is not None:
                raise RuntimeError(
                    f"No DNA found for '{client.name}' — run /admin/seed/dna first"
                )
            log.warning("watchlist.no_dna_skipping", client=client.name)
            continue

        positions = (
            await session.execute(
                select(Position).where(Position.client_id == client.id)
            )
        ).scalars().all()

        if not positions:
            if client_id is not None:
                raise RuntimeError(
                    f"No positions found for '{client.name}' — run /admin/seed/portfolio first"
                )
            log.warning("watchlist.no_positions_skipping", client=client.name)
            continue

        entities = _build_entities(positions)
        themes = _build_themes(dna)
        keywords = _build_keywords(entities, themes)

        stmt = (
            pg_insert(ClientWatchlist)
            .values(
                client_id=client.id,
                entities=entities,
                themes=themes,
                keywords=keywords,
            )
            .on_conflict_do_update(
                index_elements=["client_id"],
                set_={"entities": entities, "themes": themes, "keywords": keywords},
            )
        )
        await session.execute(stmt)
        await session.commit()

        log.info(
            "watchlist.client_built",
            client=client.name,
            entities=len(entities),
            themes=len(themes),
            keywords=len(keywords),
        )
        results[client.name] = 1

    log.info("watchlist.build_complete", clients=len(results))
    return results


async def get_global_index(session: AsyncSession) -> dict:
    """Return the union of all clients' keywords for the news poller (§14.2 F1).

    Returns {"keywords": [...], "client_count": N, "keyword_count": N}.
    """
    rows = (await session.execute(select(ClientWatchlist))).scalars().all()
    all_keywords = list(
        dict.fromkeys(kw for row in rows for kw in (row.keywords or []))
    )
    return {
        "keywords": all_keywords,
        "client_count": len(rows),
        "keyword_count": len(all_keywords),
    }


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------


def _build_entities(positions: list[Position]) -> list[dict]:
    """Deduplicated entity list from positions, keyed by ISIN (fallback: issuer)."""
    seen: dict[str, dict] = {}
    for pos in positions:
        key = pos.isin if pos.isin else pos.issuer
        if key is None or key in seen:
            continue
        seen[key] = {
            "issuer": pos.issuer,
            "isin": pos.isin,
            "valor": pos.valor,
            "ticker": pos.yahoo,
        }
    return list(seen.values())


def _build_themes(dna: ClientDNA) -> list[str]:
    """Deduplicated DNA theme tag tokens from exclusions + tilts + values."""
    all_attrs = (dna.exclusions or []) + (dna.tilts or []) + (dna.values or [])
    tags = [item["tag"] for item in all_attrs if item.get("tag")]
    return list(dict.fromkeys(tags))


def _build_keywords(entities: list[dict], themes: list[str]) -> list[str]:
    """Flat deduplicated list of all searchable strings: entity names + themes."""
    raw: list[str] = []
    for entity in entities:
        if entity.get("issuer"):
            raw.append(entity["issuer"])
        if entity.get("ticker"):
            raw.append(entity["ticker"])
        if entity.get("isin"):
            raw.append(entity["isin"])
    raw.extend(themes)
    return [kw for kw in list(dict.fromkeys(raw)) if kw]
