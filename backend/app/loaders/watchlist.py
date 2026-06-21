"""Per-client watchlist builder (TASK-027, EPIC-06).

Derives, per client, a watchlist = held entities (issuer/ticker/ISIN from
positions) UNION DNA themes (tag tokens from client_dna.exclusions/tilts/values).
Stores the result in client_watchlists (one row per client, idempotent upsert).

Also exposes get_global_index() — the union of all clients' keywords — which
TASK-029's sequential poller uses as the single Event Registry feed filter (§14.2 F1).

Seeding order: seed/portfolio → seed/dna → seed/watchlist
"""

import uuid
from collections import Counter

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.loaders.news_match import significant_name_tokens
from app.logging import get_logger
from app.models.derived import ClientDNA, ClientWatchlist
from app.models.source import Client, Position

log = get_logger(__name__)
settings = get_settings()


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
    """Return the global news-firehose filter for the poller (§14.2 F1).

    Event Registry caps the keyword count per query (hackathon tier = 80), so the
    naive union of every client's keywords (issuer + ticker + ISIN per holding, ~500
    tokens) is rejected. We instead build the filter from **issuer names + DNA themes
    only** — ISIN/ticker tokens almost never appear in news prose — and rank by
    *cross-client breadth*: a name held by many clients is the highest-value filter
    because news on it fans out to many clients (the multi-client events the radar is
    built around). The list is truncated to `news_max_keywords`; what's dropped is
    logged (no silent truncation).

    Returns {"keywords": [...], "client_count": N, "keyword_count": N}.
    """
    rows = (await session.execute(select(ClientWatchlist))).scalars().all()

    # Count how many clients carry each issuer name / theme (breadth = relevance).
    # Issuer names with no distinctive token ("Swiss Bank", "US Treasury", "ZKB Bond")
    # are dropped — as news-search terms they only return firehose noise. DNA themes
    # are kept verbatim (curated, may be short like "esg").
    breadth: Counter[str] = Counter()
    for row in rows:
        names: set[str] = set()
        for entity in row.entities or []:
            issuer = entity.get("issuer")
            if issuer and significant_name_tokens(issuer):
                names.add(issuer)
        for tag in row.themes or []:
            if tag:
                names.add(tag)
        breadth.update(names)

    # Most-widely-held first, then alphabetical for stable, reproducible ordering.
    ranked = [kw for kw, _ in sorted(breadth.items(), key=lambda kv: (-kv[1], kv[0]))]
    limit = settings.news_max_keywords
    keywords = ranked[:limit]
    if len(ranked) > limit:
        log.info(
            "watchlist.global_index_capped",
            total=len(ranked),
            kept=len(keywords),
            limit=limit,
            dropped=len(ranked) - limit,
        )

    return {
        "keywords": keywords,
        "client_count": len(rows),
        "keyword_count": len(keywords),
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
    """Search keywords for the Event Registry API: significant issuer tokens + DNA themes.

    ISINs and tickers are excluded — they never appear in news headlines (§14.1).
    Multi-word issuer names are decomposed into their significant single tokens so
    that each keyword counts as one word against the API's per-query limit.
    """
    seen: set[str] = set()
    raw: list[str] = []
    for entity in entities:
        for tok in significant_name_tokens(entity.get("issuer")):
            if tok not in seen:
                seen.add(tok)
                raw.append(tok)
    for tag in themes:
        if tag and tag not in seen:
            seen.add(tag)
            raw.append(tag)
    return raw
