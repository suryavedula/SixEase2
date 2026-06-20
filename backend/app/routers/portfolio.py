"""Portfolio read endpoints (TASK-020/021, EPIC-05).

Exposes per-holding fit scores, portfolio aggregate (TASK-020), and DNA-conflict
swap proposals (TASK-021) for a client.

Both endpoints return gracefully when the relevant seed hasn't run yet (empty /
null state) so the frontend can render a loading state without erroring.
"""

import uuid
from collections import defaultdict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.logging import get_logger
from app.models.derived import ClientWatchlist, EnrichedHolding, SwapProposal
from app.models.source import CIORecommendation, Client, MandateStrategy, Position

router = APIRouter(prefix="/clients", tags=["portfolio"])
log = get_logger(__name__)


class HoldingFit(BaseModel):
    position_id: str
    issuer: str | None
    security: str | None
    industry_group: str | None
    sub_asset_class: str | None
    valor: str | None
    current_chf: float | None
    tags: dict | None
    fit_score: float | None
    conflicts: list | None
    cio_view: str | None


class PortfolioFitResponse(BaseModel):
    client_id: str
    client_name: str
    mandate: str
    portfolio_fit: float | None
    holdings: list[HoldingFit]
    total_holdings: int
    scored_holdings: int


@router.get("/{client_id}/portfolio/fit", response_model=PortfolioFitResponse)
async def get_portfolio_fit(
    client_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> PortfolioFitResponse:
    """Return per-holding fit scores and value-weighted portfolio aggregate.

    Requires seed/fit to have run first; returns scored_holdings=0 gracefully otherwise.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    cio_view_sq = (
        select(CIORecommendation.cio_view)
        .where(
            CIORecommendation.industry_group == Position.industry_group,
            CIORecommendation.rating == "BUY",
        )
        .limit(1)
        .correlate(Position)
        .scalar_subquery()
    )

    pairs_result = await session.execute(
        select(Position, EnrichedHolding, cio_view_sq.label("cio_view"))
        .join(EnrichedHolding, Position.id == EnrichedHolding.position_id)
        .where(Position.client_id == client_id)
    )

    holdings: list[HoldingFit] = []
    weighted_sum = 0.0
    weight_total = 0.0

    for position, holding, cio_view in pairs_result.all():
        chf = float(position.current_chf) if position.current_chf is not None else None
        score = holding.fit_score

        holdings.append(
            HoldingFit(
                position_id=str(position.id),
                issuer=position.issuer,
                security=position.security,
                industry_group=position.industry_group,
                sub_asset_class=position.sub_asset_class,
                valor=position.valor,
                current_chf=chf,
                tags=holding.tags,
                fit_score=score,
                conflicts=holding.conflicts,
                cio_view=cio_view,
            )
        )

        if chf is not None and score is not None:
            weighted_sum += chf * score
            weight_total += chf

    portfolio_fit = (weighted_sum / weight_total) if weight_total > 0 else None
    scored = sum(1 for h in holdings if h.fit_score is not None)

    log.info(
        "portfolio.fit_read",
        client_id=str(client_id),
        client_name=client.name,
        holdings=len(holdings),
        scored=scored,
        portfolio_fit=portfolio_fit,
    )

    return PortfolioFitResponse(
        client_id=str(client_id),
        client_name=client.name,
        mandate=client.mandate.value,
        portfolio_fit=portfolio_fit,
        holdings=holdings,
        total_holdings=len(holdings),
        scored_holdings=scored,
    )


# ---------------------------------------------------------------------------
# Swap proposals (TASK-021)
# ---------------------------------------------------------------------------


class SwapCandidate(BaseModel):
    candidate_isin: str | None
    candidate_valor: str | None
    candidate_issuer: str | None
    candidate_security: str | None
    candidate_cio_view: str | None
    fit_gain: float | None
    dna_reason: str | None
    mandate_neutral: bool
    sources: list | None


class PositionSwaps(BaseModel):
    position_id: str
    issuer: str | None
    security: str | None
    industry_group: str | None
    sub_asset_class: str | None
    current_chf: float | None
    current_fit_score: float | None
    conflict_tags: list | None
    candidates: list[SwapCandidate]


class KeptPosition(BaseModel):
    position_id: str
    issuer: str | None
    security: str | None
    industry_group: str | None
    sub_asset_class: str | None
    current_chf: float | None
    current_fit_score: float | None
    conflict_tags: list | None
    keep_reason: str | None


class SwapProposalsResponse(BaseModel):
    client_id: str
    client_name: str
    mandate: str
    conflict_positions: int
    total_proposals: int
    positions: list[PositionSwaps]
    kept_positions: list[KeptPosition]


@router.get("/{client_id}/portfolio/swaps", response_model=SwapProposalsResponse)
async def get_portfolio_swaps(
    client_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> SwapProposalsResponse:
    """Return stored swap proposals grouped by conflict position.

    Returns positions=[] gracefully if seed/swap has not been run yet.
    Candidates within each position are ordered by fit_gain descending.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    # All swap proposals for this client's positions, with joined context
    rows_result = await session.execute(
        select(SwapProposal, Position, EnrichedHolding, CIORecommendation)
        .join(Position, SwapProposal.holding_id == Position.id)
        .join(EnrichedHolding, Position.id == EnrichedHolding.position_id)
        .outerjoin(
            CIORecommendation,
            SwapProposal.candidate_isin == CIORecommendation.isin,
        )
        .where(Position.client_id == client_id)
        .order_by(SwapProposal.fit_gain.desc().nulls_last())
    )
    rows = rows_result.all()

    # Group by position_id — real proposals vs E11 keep decisions
    position_map: dict[str, PositionSwaps] = {}
    kept_map: dict[str, KeptPosition] = {}

    for proposal, position, holding, cio in rows:
        pid = str(position.id)

        if proposal.candidate_isin is None:
            # E11 keep record — position reviewed but no compliant swap found
            if pid not in kept_map:
                kept_map[pid] = KeptPosition(
                    position_id=pid,
                    issuer=position.issuer,
                    security=position.security,
                    industry_group=position.industry_group,
                    sub_asset_class=position.sub_asset_class,
                    current_chf=float(position.current_chf) if position.current_chf else None,
                    current_fit_score=holding.fit_score,
                    conflict_tags=holding.conflicts,
                    keep_reason=proposal.dna_reason,
                )
        else:
            # Real swap proposal
            if pid not in position_map:
                position_map[pid] = PositionSwaps(
                    position_id=pid,
                    issuer=position.issuer,
                    security=position.security,
                    industry_group=position.industry_group,
                    sub_asset_class=position.sub_asset_class,
                    current_chf=float(position.current_chf) if position.current_chf else None,
                    current_fit_score=holding.fit_score,
                    conflict_tags=holding.conflicts,
                    candidates=[],
                )
            position_map[pid].candidates.append(
                SwapCandidate(
                    candidate_isin=proposal.candidate_isin,
                    candidate_valor=proposal.candidate_valor,
                    candidate_issuer=cio.issuer if cio else None,
                    candidate_security=cio.security if cio else None,
                    candidate_cio_view=proposal.cio_view,
                    fit_gain=proposal.fit_gain,
                    dna_reason=proposal.dna_reason,
                    mandate_neutral=proposal.mandate_neutral,
                    sources=proposal.sources,
                )
            )

    positions = list(position_map.values())
    kept_positions = list(kept_map.values())
    total = sum(len(p.candidates) for p in positions)

    log.info(
        "portfolio.swaps_read",
        client_id=str(client_id),
        client_name=client.name,
        conflict_positions=len(positions),
        total_proposals=total,
        kept_count=len(kept_positions),
    )

    return SwapProposalsResponse(
        client_id=str(client_id),
        client_name=client.name,
        mandate=client.mandate.value,
        conflict_positions=len(positions),
        total_proposals=total,
        positions=positions,
        kept_positions=kept_positions,
    )


# ---------------------------------------------------------------------------
# Portfolio allocation (TASK-025)
# ---------------------------------------------------------------------------

DRIFT_BREACH_PP: float = 2.0


class SACRow(BaseModel):
    sub_asset_class: str
    current_chf: float
    current_pct: float
    target_pct: float
    drift_pp: float
    breach: bool


class AllocationResponse(BaseModel):
    client_id: str
    client_name: str
    mandate: str
    total_chf: float
    sac_rows: list[SACRow]


@router.get("/{client_id}/portfolio/allocation", response_model=AllocationResponse)
async def get_portfolio_allocation(
    client_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> AllocationResponse:
    """Return sub-asset-class allocation vs mandate targets.

    Used by AllocationDonut, DriftBars, and SectorTreemap widgets.
    Returns sac_rows=[] gracefully if no positions are seeded.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    # Current allocation: one aggregate row per sub_asset_class
    sac_result = await session.execute(
        select(Position.sub_asset_class, func.sum(Position.current_chf).label("chf"))
        .where(Position.client_id == client_id, Position.current_chf.isnot(None))
        .group_by(Position.sub_asset_class)
    )
    sac_chf: dict[str, float] = {
        row.sub_asset_class.strip(): float(row.chf)
        for row in sac_result
        if row.sub_asset_class is not None
    }

    total_chf = sum(sac_chf.values())

    # Target weights from mandate strategy (exclude the "GLOBAL MANDATE" header row
    # which represents the 100% total and is not a real sub-asset-class)
    strategy_result = await session.execute(
        select(MandateStrategy).where(
            MandateStrategy.mandate == client.mandate,
            MandateStrategy.sub_asset_class != "GLOBAL MANDATE",
        )
    )
    target_weights: dict[str, float] = {
        row.sub_asset_class.strip(): float(row.target_weight)
        for row in strategy_result.scalars().all()
    }

    # Merge: include all SACs that appear in positions or strategy
    all_sacs = sorted(set(sac_chf) | set(target_weights))
    rows: list[SACRow] = []
    for sac in all_sacs:
        current_chf = sac_chf.get(sac, 0.0)
        current_pct = (current_chf / total_chf * 100) if total_chf > 0 else 0.0
        target_pct = target_weights.get(sac, 0.0)
        drift_pp = current_pct - target_pct
        rows.append(
            SACRow(
                sub_asset_class=sac,
                current_chf=round(current_chf, 2),
                current_pct=round(current_pct, 4),
                target_pct=round(target_pct, 4),
                drift_pp=round(drift_pp, 4),
                breach=abs(drift_pp) > DRIFT_BREACH_PP,
            )
        )

    # Sort by |drift_pp| desc so the most breached SAC comes first
    rows.sort(key=lambda r: abs(r.drift_pp), reverse=True)

    log.info(
        "portfolio.allocation_read",
        client_id=str(client_id),
        client_name=client.name,
        total_chf=total_chf,
        sac_count=len(rows),
        breaches=sum(1 for r in rows if r.breach),
    )

    return AllocationResponse(
        client_id=str(client_id),
        client_name=client.name,
        mandate=client.mandate.value,
        total_chf=round(total_chf, 2),
        sac_rows=rows,
    )


# ---------------------------------------------------------------------------
# Live-priced portfolio view (TASK-026)
# ---------------------------------------------------------------------------


class LiveHolding(BaseModel):
    position_id: str
    issuer: str | None
    security: str | None
    sub_asset_class: str | None
    industry_group: str | None
    valor: str | None
    isin: str | None
    yahoo: str | None
    quantity: float | None
    live_price: float | None
    live_price_at: str | None
    live_chf: float | None
    current_chf: float | None
    is_live: bool


class SacWeight(BaseModel):
    sub_asset_class: str
    live_chf: float
    weight_pct: float
    target_pct: float
    drift_pp: float
    is_breach: bool


class PortfolioLiveResponse(BaseModel):
    client_id: str
    client_name: str
    mandate: str
    total_live_chf: float
    live_price_count: int
    fallback_count: int
    holdings: list[LiveHolding]
    sac_weights: list[SacWeight]


@router.get("/{client_id}/portfolio/live", response_model=PortfolioLiveResponse)
async def get_portfolio_live(
    client_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> PortfolioLiveResponse:
    """Return per-holding live prices with sub-asset-class weights vs mandate targets.

    Uses enriched_holdings.live_price × positions.quantity when live data is available;
    falls back to positions.current_chf otherwise. Returns gracefully before seed/enrich
    has run (all is_live=False). Feeds the drift-bar widget and live-price holdings table.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    pairs_result = await session.execute(
        select(Position, EnrichedHolding)
        .join(EnrichedHolding, Position.id == EnrichedHolding.position_id)
        .where(Position.client_id == client_id)
    )
    pairs = pairs_result.all()

    strategy_result = await session.execute(
        select(MandateStrategy).where(
            MandateStrategy.mandate == client.mandate,
            MandateStrategy.sub_asset_class != "GLOBAL MANDATE",
        )
    )
    target_weights: dict[str, float] = {
        row.sub_asset_class.strip(): float(row.target_weight)
        for row in strategy_result.scalars().all()
    }

    holdings: list[LiveHolding] = []
    sac_live_chf: dict[str, float] = defaultdict(float)
    live_count = fallback_count = 0

    for position, holding in pairs:
        qty = float(position.quantity) if position.quantity is not None else None
        price = float(holding.live_price) if holding.live_price is not None else None
        current = float(position.current_chf) if position.current_chf is not None else None

        if price is not None and qty is not None:
            live_chf = price * qty
            is_live = True
            live_count += 1
        else:
            live_chf = current
            is_live = False
            fallback_count += 1

        if live_chf is not None and position.sub_asset_class:
            sac_live_chf[position.sub_asset_class.strip()] += live_chf

        holdings.append(
            LiveHolding(
                position_id=str(position.id),
                issuer=position.issuer,
                security=position.security,
                sub_asset_class=position.sub_asset_class,
                industry_group=position.industry_group,
                valor=position.valor,
                isin=position.isin,
                yahoo=position.yahoo,
                quantity=qty,
                live_price=price,
                live_price_at=(
                    holding.live_price_at.isoformat()
                    if holding.live_price_at is not None
                    else None
                ),
                live_chf=round(live_chf, 2) if live_chf is not None else None,
                current_chf=round(current, 2) if current is not None else None,
                is_live=is_live,
            )
        )

    total_live_chf = sum(sac_live_chf.values())
    all_sacs = sorted(set(sac_live_chf) | set(target_weights))
    sac_weights: list[SacWeight] = []
    for sac in all_sacs:
        chf = sac_live_chf.get(sac, 0.0)
        weight_pct = (chf / total_live_chf * 100) if total_live_chf > 0 else 0.0
        target_pct = target_weights.get(sac, 0.0)
        drift_pp = weight_pct - target_pct
        sac_weights.append(
            SacWeight(
                sub_asset_class=sac,
                live_chf=round(chf, 2),
                weight_pct=round(weight_pct, 4),
                target_pct=round(target_pct, 4),
                drift_pp=round(drift_pp, 4),
                is_breach=abs(drift_pp) > DRIFT_BREACH_PP,
            )
        )
    sac_weights.sort(key=lambda w: abs(w.drift_pp), reverse=True)

    log.info(
        "portfolio.live_read",
        client_id=str(client_id),
        client_name=client.name,
        total_live_chf=total_live_chf,
        live_count=live_count,
        fallback_count=fallback_count,
    )

    return PortfolioLiveResponse(
        client_id=str(client_id),
        client_name=client.name,
        mandate=client.mandate.value,
        total_live_chf=round(total_live_chf, 2),
        live_price_count=live_count,
        fallback_count=fallback_count,
        holdings=holdings,
        sac_weights=sac_weights,
    )


# ---------------------------------------------------------------------------
# Per-client watchlist (TASK-027)
# ---------------------------------------------------------------------------


class WatchlistResponse(BaseModel):
    client_id: str
    client_name: str
    entities: list | None
    themes: list | None
    keywords: list | None


@router.get("/{client_id}/watchlist", response_model=WatchlistResponse)
async def get_client_watchlist(
    client_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> WatchlistResponse:
    """Return per-client watchlist (entities + themes + keywords) for news query construction.

    Returns entities/themes/keywords=None gracefully if seed/watchlist has not been run.
    """
    client = await session.get(Client, client_id)
    if client is None:
        raise HTTPException(status_code=404, detail="Client not found")

    wl = await session.scalar(
        select(ClientWatchlist).where(ClientWatchlist.client_id == client_id)
    )

    log.info(
        "portfolio.watchlist_read",
        client_id=str(client_id),
        client_name=client.name,
        has_watchlist=wl is not None,
    )

    return WatchlistResponse(
        client_id=str(client_id),
        client_name=client.name,
        entities=wl.entities if wl else None,
        themes=wl.themes if wl else None,
        keywords=wl.keywords if wl else None,
    )
