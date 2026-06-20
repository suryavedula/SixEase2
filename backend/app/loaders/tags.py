"""Instrument value-tagging loader (TASK-010, EPIC-02).

Annotates positions → enriched_holdings.tags and CIO rows → cio_recommendations.tags
from the static map in app.tags. Requires seed/portfolio to have run first.

Called from POST /admin/seed/tags via app.routers.admin.
"""

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models.derived import EnrichedHolding
from app.models.source import CIORecommendation, Position
from app.tags import instrument_tags

log = get_logger(__name__)


async def load_tags(session: AsyncSession) -> dict[str, int]:
    """Annotate all instruments with region/sector/value tags. Single commit at the end."""
    n_positions = await _tag_positions(session)
    n_cio = await _tag_cio(session)
    await session.commit()
    log.info("tags.load_complete", positions_tagged=n_positions, cio_tagged=n_cio)
    return {"positions_tagged": n_positions, "cio_tagged": n_cio}


async def _tag_positions(session: AsyncSession) -> int:
    result = await session.execute(
        select(Position.id, Position.industry_group, Position.region)
    )
    rows = result.all()
    if not rows:
        raise RuntimeError("No positions found — run /admin/seed/portfolio first")

    for position_id, industry_group, region in rows:
        tags = instrument_tags(industry_group, region)
        stmt = (
            pg_insert(EnrichedHolding)
            .values(position_id=position_id, tags=tags)
            .on_conflict_do_update(
                index_elements=["position_id"],
                set_={"tags": tags},
            )
        )
        await session.execute(stmt)

    log.info("tags.positions_tagged", count=len(rows))
    return len(rows)


async def _tag_cio(session: AsyncSession) -> int:
    result = await session.execute(
        select(CIORecommendation.id, CIORecommendation.industry_group, CIORecommendation.region)
    )
    rows = result.all()

    for row_id, industry_group, region in rows:
        tags = instrument_tags(industry_group, region)
        await session.execute(
            update(CIORecommendation)
            .where(CIORecommendation.id == row_id)
            .values(tags=tags)
        )

    log.info("tags.cio_tagged", count=len(rows))
    return len(rows)
