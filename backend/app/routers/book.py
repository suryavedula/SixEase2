"""Book-level aggregated view across all clients (TASK-024, EPIC-05).

Returns all clients sorted by value-weighted portfolio fit score, each with
a ranked swap-proposal queue summary. Demonstrates personalisation at scale
from a single fixed strategy (§12 D4).

Seeding order required for full data:
  seed/portfolio → seed/tags → seed/synthetic → seed/dna → seed/fit → seed/swap
"""

from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.logging import get_logger
from app.models.derived import EnrichedHolding, SwapProposal
from app.models.enums import Mandate
from app.models.source import CIORecommendation, Client, Position

router = APIRouter(prefix="/book", tags=["book"])
log = get_logger(__name__)


class BookSwapSummary(BaseModel):
    position_id: str
    from_security: str | None
    to_security: str | None
    fit_gain: float | None
    dna_reason: str | None


class BookClient(BaseModel):
    client_id: str
    client_name: str
    mandate: str
    portfolio_fit: float | None
    total_positions: int
    conflict_positions: int
    proposal_count: int
    kept_count: int
    top_swaps: list[BookSwapSummary]


class BookResponse(BaseModel):
    total_clients: int
    scored_clients: int
    clients: list[BookClient]


@router.get("", response_model=BookResponse)
async def get_book(
    mandate: str | None = Query(default=None, description="Filter by DEFENSIVE / BALANCED / GROWTH"),
    session: AsyncSession = Depends(get_session),
) -> BookResponse:
    """Return all clients sorted by portfolio fit, each with their swap proposal queue.

    Aggregates fit and swap data across ~107 clients in two queries (no N+1).
    Clients without scored holdings return portfolio_fit=None and sort last.
    Returns gracefully when seeding has not yet run.
    """
    mandate_enum: Mandate | None = None
    if mandate is not None:
        try:
            mandate_enum = Mandate[mandate.upper()]
        except KeyError:
            raise HTTPException(
                status_code=422,
                detail=f"Invalid mandate '{mandate}'. Valid values: {[m.name for m in Mandate]}",
            )

    weighted_num = func.sum(
        case(
            (EnrichedHolding.fit_score.isnot(None), Position.current_chf * EnrichedHolding.fit_score),
            else_=0.0,
        )
    )
    weighted_den = func.nullif(
        func.sum(
            case(
                (EnrichedHolding.fit_score.isnot(None), Position.current_chf),
                else_=0.0,
            )
        ),
        0.0,
    )
    conflict_count = func.sum(case((EnrichedHolding.fit_score == 0.0, 1), else_=0))
    total_count = func.count(Position.id)

    stmt = (
        select(
            Client.id,
            Client.name,
            Client.mandate,
            total_count.label("total_positions"),
            (weighted_num / weighted_den).label("portfolio_fit"),
            conflict_count.label("conflict_positions"),
        )
        .outerjoin(Position, Position.client_id == Client.id)
        .outerjoin(EnrichedHolding, EnrichedHolding.position_id == Position.id)
        .group_by(Client.id, Client.name, Client.mandate)
    )
    if mandate_enum is not None:
        stmt = stmt.where(Client.mandate == mandate_enum)

    rows = (await session.execute(stmt)).all()

    client_ids = [row.id for row in rows]

    real_swaps: dict[str, list] = defaultdict(list)
    kept_counts: dict[str, int] = defaultdict(int)

    if client_ids:
        swap_stmt = (
            select(
                SwapProposal.candidate_isin,
                SwapProposal.fit_gain,
                SwapProposal.dna_reason,
                Position.id.label("position_id"),
                Position.client_id,
                Position.security.label("from_security"),
                CIORecommendation.security.label("to_security"),
            )
            .join(Position, SwapProposal.holding_id == Position.id)
            .outerjoin(CIORecommendation, SwapProposal.candidate_isin == CIORecommendation.isin)
            .where(Position.client_id.in_(client_ids))
            .order_by(Position.client_id, SwapProposal.fit_gain.desc().nulls_last())
        )
        swap_rows = (await session.execute(swap_stmt)).all()

        for row in swap_rows:
            cid = str(row.client_id)
            if row.candidate_isin is None:
                kept_counts[cid] += 1
            else:
                real_swaps[cid].append(row)

    clients_out: list[BookClient] = []
    for row in rows:
        cid = str(row.id)
        swaps = real_swaps[cid]
        top = [
            BookSwapSummary(
                position_id=str(s.position_id),
                from_security=s.from_security,
                to_security=s.to_security,
                fit_gain=float(s.fit_gain) if s.fit_gain is not None else None,
                dna_reason=s.dna_reason,
            )
            for s in swaps[:3]
        ]
        pf = float(row.portfolio_fit) if row.portfolio_fit is not None else None
        clients_out.append(
            BookClient(
                client_id=cid,
                client_name=row.name,
                mandate=row.mandate.value,
                portfolio_fit=pf,
                total_positions=int(row.total_positions or 0),
                conflict_positions=int(row.conflict_positions or 0),
                proposal_count=len(swaps),
                kept_count=kept_counts[cid],
                top_swaps=top,
            )
        )

    clients_out.sort(key=lambda c: (c.portfolio_fit is None, -(c.portfolio_fit or 0.0)))

    scored = sum(1 for c in clients_out if c.portfolio_fit is not None)
    log.info("book.read", total_clients=len(clients_out), scored_clients=scored, mandate=mandate)

    return BookResponse(
        total_clients=len(clients_out),
        scored_clients=scored,
        clients=clients_out,
    )
