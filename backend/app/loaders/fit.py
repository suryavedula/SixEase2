"""Fit-score engine (TASK-020, EPIC-05).

Computes deterministic per-holding fit scores by matching client DNA exclusions
and tilts against instrument value_tags stored in enriched_holdings. Writes
fit_score (Float) and conflicts (JSONB breakdown) to enriched_holdings. The
portfolio-level aggregate is value-weighted and computed at read time (not stored).

No LLM calls — purely deterministic arithmetic (§11 E7).

Seeding order: seed/portfolio → seed/tags → seed/dna → seed/fit
"""

import uuid

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models.derived import ClientDNA, EnrichedHolding
from app.models.source import Client, Position

log = get_logger(__name__)

BASE_SCORE: float = 0.5
TILT_BONUS: float = 0.25
EXCLUSION_SCORE: float = 0.0


def _score_holding(
    value_tags: list[str],
    exclusion_tags: frozenset[str],
    tilt_tags: frozenset[str],
) -> tuple[float, list[dict]]:
    """Return (score, breakdown) for one holding. Pure function; no I/O."""
    breakdown: list[dict] = []
    for tag in value_tags:
        if tag in exclusion_tags:
            breakdown.append({"tag": tag, "impact": "exclusion", "direction": -1})
        elif tag in tilt_tags:
            breakdown.append({"tag": tag, "impact": "tilt", "direction": 1})

    if any(b["impact"] == "exclusion" for b in breakdown):
        return EXCLUSION_SCORE, breakdown

    tilt_hits = sum(1 for b in breakdown if b["impact"] == "tilt")
    return min(1.0, BASE_SCORE + tilt_hits * TILT_BONUS), breakdown


async def compute_fit(
    session: AsyncSession,
    client_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Compute fit scores for all clients (or one if client_id provided).

    Commits once per client so a failure on client N does not roll back N-1.
    Returns {"clients_scored": N, "holdings_scored": M}.
    """
    if client_id is not None:
        clients_result = await session.execute(
            select(Client).where(Client.id == client_id)
        )
    else:
        clients_result = await session.execute(select(Client))
    clients = clients_result.scalars().all()

    total_holdings = 0

    for client in clients:
        dna = await session.scalar(
            select(ClientDNA).where(ClientDNA.client_id == client.id)
        )
        if dna is None:
            if client_id is not None:
                raise RuntimeError(
                    f"No DNA found for '{client.name}' — run /admin/seed/dna first"
                )
            log.warning("fit.no_dna_skipping", client=client.name)
            continue

        exclusion_tags: frozenset[str] = frozenset(
            item["tag"] for item in (dna.exclusions or []) if item.get("tag")
        )
        tilt_tags: frozenset[str] = frozenset(
            item["tag"] for item in (dna.tilts or []) if item.get("tag")
        )

        pairs_result = await session.execute(
            select(Position, EnrichedHolding)
            .join(EnrichedHolding, Position.id == EnrichedHolding.position_id)
            .where(Position.client_id == client.id)
        )
        pairs = pairs_result.all()

        if not pairs:
            log.warning("fit.no_holdings", client=client.name)
            continue

        n_scored = 0
        for position, holding in pairs:
            if holding.tags is None:
                log.warning("fit.no_tags", position_id=str(position.id), client=client.name)
                value_tags: list[str] = []
            else:
                value_tags = holding.tags.get("value_tags", [])

            score, breakdown = _score_holding(value_tags, exclusion_tags, tilt_tags)

            await session.execute(
                update(EnrichedHolding)
                .where(EnrichedHolding.id == holding.id)
                .values(fit_score=score, conflicts=breakdown)
            )
            n_scored += 1

        await session.commit()
        total_holdings += n_scored
        log.info("fit.client_scored", client=client.name, holdings=n_scored)

    log.info("fit.compute_complete", clients=len(clients), holdings=total_holdings)
    return {"clients_scored": len(clients), "holdings_scored": total_holdings}
