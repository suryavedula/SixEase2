"""Fact-sheet assembler (TASK-037, EPIC-09).

Deterministically assembles the MSG2 locked fact sheet from engine + DNA + news:
  { trigger, holding, proposal, numbers, mandate_impact_unchanged,
    dna_points:[{value, tag, source_note_id}], evidence:[{headline, url}] }

No LLM is called. Every value traces to a DB column or a spec invariant (E8).
The assembled fact_sheet is stored in a new MessageDraft row (status=draft).

Seeding order: seed/portfolio → seed/crm → seed/dna → seed/tags → seed/fit →
               seed/swap → seed/alerts
               (scan/news optional — enriches evidence[] but not required)
"""

import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.loaders.channel import suggest_channel
from app.logging import get_logger
from app.models.derived import (
    Alert,
    ClientDNA,
    EnrichedHolding,
    MessageDraft,
    NewsItem,
    SwapProposal,
)
from app.models.enums import AlertStatus, DraftStatus
from app.models.source import CIORecommendation, Position

log = get_logger(__name__)


async def assemble_fact_sheet(
    session: AsyncSession,
    client_id: uuid.UUID,
    alert_id: uuid.UUID | None = None,
) -> dict:
    """Assemble the MSG2 fact sheet for a client and store it as a MessageDraft.

    If alert_id is given, anchors to that specific alert.
    Otherwise picks the most recent open dna_conflict alert for the client.

    Returns {"draft_id": str, "client_id": str, "fact_sheet": {...}, "has_proposal": bool}.
    Raises RuntimeError if prerequisites are missing.
    """
    # 1. Load ClientDNA — prerequisite for dna_points + style
    dna = await session.scalar(
        select(ClientDNA).where(ClientDNA.client_id == client_id)
    )
    if dna is None:
        raise RuntimeError(
            f"No DNA found for client {client_id} — run /admin/seed/dna first"
        )

    # 2. Resolve alert
    if alert_id is not None:
        alert = await session.scalar(
            select(Alert).where(Alert.id == alert_id, Alert.client_id == client_id)
        )
        if alert is None:
            raise RuntimeError(f"Alert {alert_id} not found for client {client_id}")
    else:
        alert = await session.scalar(
            select(Alert)
            .where(
                Alert.client_id == client_id,
                Alert.alert_class == "dna_conflict",
                Alert.status == AlertStatus.OPEN,
            )
            .order_by(Alert.created_at.desc())
            .limit(1)
        )
        if alert is None:
            raise RuntimeError(
                f"No open dna_conflict alert for client {client_id} "
                "— run /admin/seed/alerts first"
            )

    # 3. Resolve the anchor position from alert evidence. dna_conflict/drift/swap
    # alerts carry the holding's isin/valor at the top level; news_impact/panic
    # reach-outs instead carry the held position(s) under matched_holdings — anchor
    # to the first held match there.
    evidence_item = (alert.evidence or [{}])[0]
    conflict_isin = evidence_item.get("isin")
    conflict_valor = evidence_item.get("valor")
    if not conflict_isin and not conflict_valor:
        matched = evidence_item.get("matched_holdings") or []
        if matched:
            conflict_isin = matched[0].get("isin")
            conflict_valor = matched[0].get("valor")

    position = None
    if conflict_isin:
        position = await session.scalar(
            select(Position).where(
                Position.client_id == client_id,
                Position.isin == conflict_isin,
            )
        )
    if position is None and conflict_valor:
        position = await session.scalar(
            select(Position).where(
                Position.client_id == client_id,
                Position.valor == conflict_valor,
            )
        )
    if position is None:
        raise RuntimeError(
            f"This {alert.alert_class} alert isn't anchored to a holding, so there's "
            "no portfolio fact sheet to draft from. Grounded drafts are built around "
            "a specific position (a values conflict, drift, or a news event on a held "
            "name)."
        )

    enriched = await session.scalar(
        select(EnrichedHolding).where(EnrichedHolding.position_id == position.id)
    )
    conflict_tags: set[str] = set()
    if enriched and enriched.conflicts:
        conflict_tags = {
            b["tag"]
            for b in enriched.conflicts
            if b.get("impact") == "exclusion" and b.get("tag")
        }

    # 4. Resolve best swap proposal (highest fit_gain with a real candidate)
    proposal_row = await session.scalar(
        select(SwapProposal)
        .where(
            SwapProposal.holding_id == position.id,
            SwapProposal.candidate_isin.isnot(None),
        )
        .order_by(SwapProposal.fit_gain.desc())
        .limit(1)
    )

    proposal_block = None
    if proposal_row is not None:
        cio = await session.scalar(
            select(CIORecommendation).where(
                CIORecommendation.isin == proposal_row.candidate_isin
            )
        )
        proposal_block = {
            "candidate_isin": proposal_row.candidate_isin,
            "candidate_valor": proposal_row.candidate_valor,
            "candidate_issuer": cio.issuer if cio else None,
            "candidate_security": cio.security if cio else None,
            "dna_reason": proposal_row.dna_reason,
            "cio_view": proposal_row.cio_view,
            "fit_gain": (
                float(proposal_row.fit_gain)
                if proposal_row.fit_gain is not None
                else None
            ),
            "mandate_neutral": True,  # E8 invariant — always true
        }

    # 5. Compute numbers
    total_chf_raw = await session.scalar(
        select(func.sum(Position.current_chf)).where(
            Position.client_id == client_id,
            Position.current_chf.isnot(None),
        )
    )
    total_portfolio_chf = float(total_chf_raw) if total_chf_raw else 0.0
    current_chf = float(position.current_chf) if position.current_chf is not None else None
    target_chf = float(position.target_chf) if position.target_chf is not None else None
    portfolio_pct = (
        round(current_chf / total_portfolio_chf * 100, 2)
        if current_chf is not None and total_portfolio_chf > 0
        else None
    )

    # 6. Load supporting news evidence (up to 3 threat/opportunity articles for this client)
    news_rows = (
        await session.execute(
            select(NewsItem)
            .where(
                NewsItem.client_ids.contains([str(client_id)]),
                NewsItem.impact.in_(["threat", "opportunity"]),
            )
            .order_by(NewsItem.published_at.desc())
            .limit(3)
        )
    ).scalars().all()

    evidence_list = [
        {
            "headline": n.headline,
            "url": n.url,
            "impact": n.impact,
            "published_at": str(n.published_at) if n.published_at else None,
            "source_news_item_id": str(n.id),
        }
        for n in news_rows
    ]

    # 7. Build dna_points — only DNA attributes relevant to this conflict
    dna_points = []
    for item in (dna.exclusions or []) + (dna.tilts or []):
        tag = item.get("tag")
        source_ids = item.get("source_note_ids") or []
        if tag and tag in conflict_tags and source_ids:
            dna_points.append(
                {
                    "value": item.get("text", ""),
                    "tag": tag,
                    "source_note_id": source_ids[0],
                }
            )

    # 8. Assemble MSG2 fact sheet — all values sourced from DB columns or spec constants
    fact_sheet: dict = {
        "trigger": alert.trigger,
        "holding": {
            "issuer": position.issuer,
            "security": position.security,
            "isin": position.isin,
            "valor": position.valor,
            "sub_asset_class": position.sub_asset_class,
            "industry_group": position.industry_group,
            "current_chf": current_chf,
            "target_chf": target_chf,
        },
        "proposal": proposal_block,  # None when no compliant swap exists (E11 path)
        "numbers": {
            "current_chf": current_chf,
            "target_chf": target_chf,
            "fit_score": (
                float(enriched.fit_score)
                if enriched and enriched.fit_score is not None
                else None
            ),
            "portfolio_pct": portfolio_pct,
        },
        "mandate_impact_unchanged": True,  # E8 — all proposals are same-sub_asset_class
        "dna_points": dna_points,
        "evidence": evidence_list,
    }

    # 9. Persist as a new MessageDraft (new-draft-per-call; no delete-and-reload)
    channel = suggest_channel(alert.alert_class)
    draft = MessageDraft(
        client_id=client_id,
        fact_sheet=fact_sheet,
        style=str(dna.style_profile) if dna.style_profile else None,
        channel=channel,
        status=DraftStatus.DRAFT,
    )
    session.add(draft)
    await session.commit()

    log.info(
        "fact_sheet.assembled",
        client_id=str(client_id),
        draft_id=str(draft.id),
        alert_class=alert.alert_class,
        has_proposal=proposal_block is not None,
        dna_points=len(dna_points),
        evidence=len(evidence_list),
    )

    return {
        "draft_id": str(draft.id),
        "client_id": str(client_id),
        "fact_sheet": fact_sheet,
        "channel": channel,
        "has_proposal": proposal_block is not None,
    }
