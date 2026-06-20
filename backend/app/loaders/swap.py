"""Swap-candidate engine (TASK-021, EPIC-05).

For each client, finds CIO-BUY same-sector replacements for every DNA-conflict
holding (fit_score == 0.0). Candidates must:
  - be CIO BUY and not currently held by this client (E4)
  - match position's sub_asset_class + industry_group (E3)
  - not hit any of the client's own hard exclusion tags (E9)
  - improve fit score by more than FIT_GAIN_THRESHOLD (E12)

Results are stored in swap_proposals (delete-and-reload per client, idempotent).
If no compliant candidate exists for a conflict position, logs E11 and continues.

Seeding order: seed/portfolio → seed/tags → seed/crm → seed/dna → seed/fit → seed/swap
"""

import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.loaders.fit import _score_holding
from app.logging import get_logger
from app.models.derived import ClientDNA, EnrichedHolding, SwapProposal
from app.models.source import CIORecommendation, Client, Position

log = get_logger(__name__)

FIT_GAIN_THRESHOLD: float = 0.10  # E12 — no-churn gate: require ≥ 10 pp fit improvement


async def compute_swaps(
    session: AsyncSession,
    client_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Compute and store swap proposals for all clients (or one if client_id given).

    Commits once per client so a failure on client N does not roll back N-1.
    Returns {"clients_processed": N, "proposals_written": M}.
    """
    if client_id is not None:
        clients = (
            await session.execute(select(Client).where(Client.id == client_id))
        ).scalars().all()
    else:
        clients = (await session.execute(select(Client))).scalars().all()

    total_proposals = 0

    for client in clients:
        dna = await session.scalar(
            select(ClientDNA).where(ClientDNA.client_id == client.id)
        )
        if dna is None:
            if client_id is not None:
                raise RuntimeError(
                    f"No DNA found for '{client.name}' — run /admin/seed/dna first"
                )
            log.warning("swap.no_dna_skipping", client=client.name)
            continue

        exclusion_tags: frozenset[str] = frozenset(
            item["tag"] for item in (dna.exclusions or []) if item.get("tag")
        )
        tilt_tags: frozenset[str] = frozenset(
            item["tag"] for item in (dna.tilts or []) if item.get("tag")
        )

        # Per-client held ISINs (E4 — not currently held by this specific client)
        held_result = await session.execute(
            select(Position.isin).where(
                Position.client_id == client.id, Position.isin.isnot(None)
            )
        )
        client_held_isins: set[str] = {row[0] for row in held_result}

        # Conflict positions: holdings that scored 0.0 (exclusion hit)
        conflict_result = await session.execute(
            select(Position, EnrichedHolding)
            .join(EnrichedHolding, Position.id == EnrichedHolding.position_id)
            .where(
                Position.client_id == client.id,
                EnrichedHolding.fit_score == 0.0,
            )
        )
        conflict_pairs = conflict_result.all()

        if not conflict_pairs:
            scored_check = await session.scalar(
                select(EnrichedHolding.id)
                .join(Position, EnrichedHolding.position_id == Position.id)
                .where(Position.client_id == client.id, EnrichedHolding.fit_score.isnot(None))
                .limit(1)
            )
            if scored_check is None:
                if client_id is not None:
                    raise RuntimeError(
                        f"No scored holdings for '{client.name}' — run /admin/seed/fit first"
                    )
                log.warning("swap.no_scored_holdings_skipping", client=client.name)
                continue
            log.info("swap.no_conflicts", client=client.name)
            await session.commit()
            continue

        # Delete existing proposals for this client's positions before reloading
        position_ids = [pos.id for pos, _ in conflict_pairs]
        await session.execute(
            delete(SwapProposal).where(SwapProposal.holding_id.in_(position_ids))
        )

        client_proposals = 0

        for position, holding in conflict_pairs:
            conflict_tags = [
                b["tag"] for b in (holding.conflicts or []) if b.get("impact") == "exclusion"
            ]

            # E9 precedence — filter candidates in constraint order:
            # P1 mandate:      sub_asset_class preserved (slot weight unchanged, E1/E8)
            # P2 compliance:   industry_group matches (risk-neutral sector, E3)
            # P4 CIO universe: must be BUY and not held by this client (E4)
            candidates_result = await session.execute(
                select(CIORecommendation).where(
                    CIORecommendation.is_swap_candidate == True,  # noqa: E712  # P4
                    CIORecommendation.sub_asset_class == position.sub_asset_class,  # P1
                    CIORecommendation.industry_group == position.industry_group,  # P2
                    CIORecommendation.isin.notin_(client_held_isins)  # P4
                    if client_held_isins
                    else True,
                )
            )
            candidates = candidates_result.scalars().all()
            all_candidates = list(candidates)  # captured for _build_keep_reason (E11)

            scored: list[tuple[float, list[str], CIORecommendation]] = []
            for candidate in candidates:
                value_tags = (
                    candidate.tags.get("value_tags", []) if candidate.tags else []
                )
                candidate_score, _ = _score_holding(value_tags, exclusion_tags, tilt_tags)

                # P3 hard exclusion — skip if candidate hits a client exclusion tag (E9)
                if candidate_score == 0.0:
                    continue

                fit_gain = candidate_score - (holding.fit_score or 0.0)

                # P5 soft optimisation — no churn: only propose a genuine improvement (E12)
                if fit_gain <= FIT_GAIN_THRESHOLD:
                    continue

                tilt_matches = [t for t in value_tags if t in tilt_tags]
                scored.append((fit_gain, tilt_matches, candidate))

            if not scored:
                keep_reason = _build_keep_reason(
                    all_candidates, exclusion_tags, conflict_tags,
                    position.industry_group, position.sub_asset_class,
                )
                log.warning(
                    "swap.no_compliant_candidate",  # E11
                    client=client.name,
                    position_id=str(position.id),
                    industry_group=position.industry_group,
                    sub_asset_class=position.sub_asset_class,
                    conflict_tags=conflict_tags,
                    keep_reason=keep_reason,
                )
                session.add(
                    SwapProposal(
                        holding_id=position.id,
                        candidate_isin=None,
                        candidate_valor=None,
                        dna_reason=keep_reason,
                        cio_view=None,
                        mandate_neutral=True,
                        fit_gain=None,
                        sources=[{"type": "keep_reason", "text": keep_reason}],
                    )
                )
                client_proposals += 1
                continue

            # Rank by fit gain descending (E7)
            scored.sort(key=lambda t: t[0], reverse=True)

            for fit_gain, tilt_matches, candidate in scored:
                session.add(
                    SwapProposal(
                        holding_id=position.id,
                        candidate_isin=candidate.isin,
                        candidate_valor=candidate.valor,
                        dna_reason=_build_dna_reason(conflict_tags, tilt_matches),
                        cio_view=candidate.cio_view,
                        mandate_neutral=True,  # E8 — same sub_asset_class preserves slot weight
                        fit_gain=fit_gain,
                        sources=[
                            {"type": "cio_view", "text": candidate.cio_view},
                            {"type": "dna_conflict", "tags": conflict_tags},
                        ],
                    )
                )
                client_proposals += 1

        await session.commit()
        total_proposals += client_proposals
        log.info(
            "swap.client_processed",
            client=client.name,
            conflict_positions=len(conflict_pairs),
            proposals=client_proposals,
        )

    log.info(
        "swap.compute_complete",
        clients=len(clients),
        proposals=total_proposals,
    )
    return {"clients_processed": len(clients), "proposals_written": total_proposals}


def _build_dna_reason(conflict_tags: list[str], tilt_matches: list[str]) -> str:
    parts = []
    if conflict_tags:
        parts.append(f"Resolves {', '.join(conflict_tags)} exclusion")
    if tilt_matches:
        parts.append(f"aligns with {', '.join(tilt_matches)} tilt")
    return "; ".join(parts) if parts else "Better DNA fit"


def _build_keep_reason(
    all_candidates: list,
    exclusion_tags: frozenset[str],
    conflict_tags: list[str],
    industry_group: str | None,
    sub_asset_class: str | None,
) -> str:
    """Explain why no swap was proposed for this conflict position (E11)."""
    sector = f"{industry_group} ({sub_asset_class})"

    if not all_candidates:
        return f"No CIO BUY candidates in {sector}"

    n = len(all_candidates)
    exclusion_blocked = []
    for candidate in all_candidates:
        value_tags = candidate.tags.get("value_tags", []) if candidate.tags else []
        score, _ = _score_holding(value_tags, exclusion_tags, frozenset())
        if score == 0.0:
            exclusion_blocked.append(candidate)

    if len(exclusion_blocked) == n:
        hit_tags = exclusion_tags & {
            t
            for c in all_candidates
            for t in (c.tags.get("value_tags", []) if c.tags else [])
        }
        tags_str = ", ".join(sorted(hit_tags)) if hit_tags else ", ".join(sorted(exclusion_tags))
        return f"All {n} CIO BUY candidate(s) in {sector} hit the {tags_str} exclusion"

    return (
        f"All {n} candidate(s) in {sector} cleared exclusions "
        f"but fit gain ≤ {FIT_GAIN_THRESHOLD:.0%}"
    )
