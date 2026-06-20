"""Alert generation from all signals (TASK-032, EPIC-08).

Generates Alert rows for 8 non-drift signal classes per client:
  news_impact, good_news, panic         — from news_items (TASK-028)
  dna_conflict                          — from enriched_holdings where fit_score = 0
  values_drift                          — portfolio-level DNA misalignment aggregate
  quiet_client                          — last Interaction date older than QUIET_DAYS
  overdue_promise                       — ClientDNA.promises entries
  behavioural_guardrail                 — SwapProposal candidate conflicts with DNA exclusions

drift_breach and stale_sell are owned by loaders/drift.py and are NOT touched here.
Idempotent: deletes all 8 managed classes per client before re-inserting.
Commits once per client so a failure on client N does not roll back N-1.

Seeding order: seed/portfolio → seed/crm → seed/dna → seed/tags → seed/fit → seed/alerts
News signals (news_impact, good_news, panic) degrade to 0 gracefully if scan/news
(TASK-028) has not been run yet.
"""

import uuid
from datetime import date

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.loaders.alert_noise import record_cooldown, should_suppress
from app.logging import get_logger
from app.models.derived import Alert, ClientDNA, EnrichedHolding, NewsItem, SwapProposal
from app.models.enums import ActionType, AlertStatus, Severity
from app.models.source import CIORecommendation, Client, Interaction, Position

log = get_logger(__name__)

QUIET_DAYS: int = 60
QUIET_CRITICAL_DAYS: int = 120
VALUES_DRIFT_THRESHOLD: float = 0.65
VALUES_DRIFT_MIN_POSITIONS: int = 3
PANIC_THRESHOLD: float = -0.5
PANIC_CRITICAL_THRESHOLD: float = -0.8

_MANAGED_CLASSES = [
    "news_impact",
    "good_news",
    "panic",
    "dna_conflict",
    "values_drift",
    "quiet_client",
    "overdue_promise",
    "behavioural_guardrail",
]


async def generate_alerts(
    session: AsyncSession,
    client_id: uuid.UUID | None = None,
) -> dict[str, int]:
    """Generate all non-drift alert classes for all clients (or one).

    Returns totals per class plus clients_processed.
    """
    if client_id is not None:
        clients = (
            await session.execute(select(Client).where(Client.id == client_id))
        ).scalars().all()
    else:
        clients = (await session.execute(select(Client))).scalars().all()

    # Load all CIO recommendations with tags once — reused per client for guardrail check
    cio_rows = (await session.execute(select(CIORecommendation))).scalars().all()
    cio_by_isin: dict[str, CIORecommendation] = {
        row.isin: row for row in cio_rows if row.isin and row.tags
    }

    totals: dict[str, int] = {c: 0 for c in _MANAGED_CLASSES}
    totals["clients_processed"] = 0

    for client in clients:
        # Idempotency: wipe this client's managed alert classes before recomputing
        await session.execute(
            delete(Alert).where(
                Alert.client_id == client.id,
                Alert.alert_class.in_(_MANAGED_CLASSES),
            )
        )

        dna = await session.scalar(
            select(ClientDNA).where(ClientDNA.client_id == client.id)
        )

        # Mutable accumulator — helpers append (alert_class, dedup_key) for each
        # alert they emit; cooldowns are recorded after commit (never before).
        emitted_keys: list[tuple[str, str]] = []

        news_counts = await _generate_news_alerts(session, client, emitted_keys)
        counts = {
            "news_impact": news_counts["news_impact"],
            "good_news": news_counts["good_news"],
            "panic": news_counts["panic"],
            "dna_conflict": await _generate_dna_conflict_alerts(session, client, emitted_keys),
            "values_drift": await _generate_values_drift_alert(session, client, emitted_keys),
            "quiet_client": await _generate_quiet_client_alert(session, client, emitted_keys),
            "overdue_promise": 0,
            "behavioural_guardrail": 0,
        }

        if dna is not None:
            counts["overdue_promise"] = await _generate_promise_alerts(
                session, client, dna, emitted_keys
            )
            counts["behavioural_guardrail"] = await _generate_guardrail_alerts(
                session, client, dna, cio_by_isin, emitted_keys
            )
        else:
            log.warning("alerts.no_dna_skipping", client=client.name)

        await session.commit()

        # Record 24h cooldowns after commit — never before (avoid persisting a
        # key for an alert that was rolled back).
        for cls, key in emitted_keys:
            await record_cooldown(client.id, cls, key)

        totals["clients_processed"] += 1
        for cls, n in counts.items():
            totals[cls] = totals.get(cls, 0) + n

        log.info("alerts.client_processed", client=client.name, **counts)

    log.info("alerts.generate_complete", **totals)
    return totals


async def _generate_news_alerts(
    session: AsyncSession,
    client: Client,
    emitted_keys: list[tuple[str, str]],
) -> dict[str, int]:
    """Generate news_impact, good_news, and panic alerts from matched news_items.

    Returns a dict with counts per sub-class.
    """
    news_rows = (
        await session.execute(
            select(NewsItem).where(
                NewsItem.client_ids.contains([str(client.id)])
            )
        )
    ).scalars().all()

    if not news_rows:
        return {"news_impact": 0, "good_news": 0, "panic": 0}

    # Split dedup keys so one event can yield both TRADE + REACH_OUT (AL2 / TASK-034).
    # Cooldown keys use action-type suffix to let the pair coexist across sessions.
    seen: dict[str, set[str | None]] = {
        "news_impact_trade": set(),
        "news_impact_reach": set(),
        "good_news": set(),
        "panic": set(),
    }
    sub_counts: dict[str, int] = {"news_impact": 0, "good_news": 0, "panic": 0}

    for item in news_rows:
        cluster = item.event_cluster_id or str(item.id)
        impact = item.impact
        sentiment = item.sentiment or 0.0
        has_own_axis = bool(item.matched_holdings)
        has_care_axis = bool(item.matched_themes)
        ev = {
            "headline": item.headline,
            "url": item.url,
            "published_at": str(item.published_at),
            "sentiment": sentiment,
        }

        # Panic signal — strongly negative own-axis article
        if sentiment <= PANIC_THRESHOLD and has_own_axis and cluster not in seen["panic"]:
            if not await should_suppress(client.id, "panic", cluster):
                seen["panic"].add(cluster)
                severity = (
                    Severity.CRITICAL if sentiment <= PANIC_CRITICAL_THRESHOLD else Severity.ATTENTION
                )
                session.add(Alert(
                    client_id=client.id,
                    alert_class="panic",
                    action_type=ActionType.REACH_OUT,
                    severity=severity,
                    status=AlertStatus.OPEN,
                    trigger=f"Negative market news (sentiment {sentiment:.2f}) on a held position",
                    why="A held position is facing strongly negative sentiment — client may need reassurance",
                    suggested_action="Proactively reach out with context before client reacts to market noise",
                    confidence=abs(sentiment),
                    evidence=[{**ev, "matched_holdings": item.matched_holdings}],
                ))
                emitted_keys.append(("panic", cluster))
                sub_counts["panic"] += 1

        # news_impact TRADE — threat/opportunity hitting a held position (own-axis)
        trade_key = cluster + "_trade"
        if impact in ("threat", "opportunity") and has_own_axis and trade_key not in seen["news_impact_trade"]:
            if not await should_suppress(client.id, "news_impact", trade_key):
                seen["news_impact_trade"].add(trade_key)
                label = "News threat" if impact == "threat" else "Portfolio opportunity"
                why_text = (
                    "A news article signals a threat relevant to this client's holdings"
                    if impact == "threat"
                    else "Positive news directly affects a held position — may warrant portfolio action"
                )
                suggestion = (
                    "Review impact on portfolio and assess if a swap or position reduction is warranted"
                    if impact == "threat"
                    else "Assess whether to increase position or lock in gains"
                )
                session.add(Alert(
                    client_id=client.id,
                    alert_class="news_impact",
                    action_type=ActionType.TRADE,
                    severity=Severity.ATTENTION,
                    status=AlertStatus.OPEN,
                    trigger=f"{label}: {item.headline or 'article'}",
                    why=why_text,
                    suggested_action=suggestion,
                    confidence=0.8,
                    evidence=[{**ev, "impact": impact, "matched_holdings": item.matched_holdings}],
                ))
                emitted_keys.append(("news_impact", trade_key))
                sub_counts["news_impact"] += 1

        # news_impact REACH_OUT — same event touches a care-axis theme (one event → two alerts)
        reach_key = cluster + "_reach"
        if impact in ("threat", "opportunity") and has_care_axis and reach_key not in seen["news_impact_reach"]:
            if not await should_suppress(client.id, "news_impact", reach_key):
                seen["news_impact_reach"].add(reach_key)
                session.add(Alert(
                    client_id=client.id,
                    alert_class="news_impact",
                    action_type=ActionType.REACH_OUT,
                    severity=Severity.ATTENTION,
                    status=AlertStatus.OPEN,
                    trigger=f"News affects client interest: {item.headline or 'article'}",
                    why="This news touches a theme the client cares about — a moment to connect personally",
                    suggested_action="Reach out with context; acknowledge the news in the client's own terms",
                    confidence=0.75,
                    evidence=[{**ev, "impact": impact, "matched_themes": item.matched_themes}],
                ))
                emitted_keys.append(("news_impact", reach_key))
                sub_counts["news_impact"] += 1

        # good_news — opportunity/moment on care-axis themes (FYI relationship moment)
        if impact in ("opportunity", "non-financial moment") and has_care_axis and cluster not in seen["good_news"]:
            if not await should_suppress(client.id, "good_news", cluster):
                seen["good_news"].add(cluster)
                session.add(Alert(
                    client_id=client.id,
                    alert_class="good_news",
                    action_type=ActionType.REACH_OUT,
                    severity=Severity.FYI,
                    status=AlertStatus.OPEN,
                    trigger=f"Good news on client interest: {item.headline or 'article'}",
                    why="A positive development touches a theme the client cares about — a relationship-building moment",
                    suggested_action="Share with client as a personalised touch; no portfolio action required",
                    confidence=0.7,
                    evidence=[{
                        "headline": item.headline,
                        "url": item.url,
                        "published_at": str(item.published_at),
                        "impact": impact,
                        "matched_themes": item.matched_themes,
                    }],
                ))
                emitted_keys.append(("good_news", cluster))
                sub_counts["good_news"] += 1

    return sub_counts


async def _generate_dna_conflict_alerts(
    session: AsyncSession,
    client: Client,
    emitted_keys: list[tuple[str, str]],
) -> int:
    """Flag held positions that violate a DNA exclusion (fit_score = 0)."""
    pairs = (
        await session.execute(
            select(Position, EnrichedHolding)
            .join(EnrichedHolding, Position.id == EnrichedHolding.position_id)
            .where(
                Position.client_id == client.id,
                EnrichedHolding.fit_score == 0.0,
            )
        )
    ).all()

    if not pairs:
        return 0

    seen: set[str] = set()
    count = 0
    for position, enriched in pairs:
        dedup_key = position.isin or str(position.id)
        if dedup_key in seen:
            continue
        if await should_suppress(client.id, "dna_conflict", dedup_key):
            continue
        seen.add(dedup_key)
        label = position.issuer or position.security or position.isin or str(position.id)
        session.add(Alert(
            client_id=client.id,
            alert_class="dna_conflict",
            action_type=ActionType.TRADE,
            severity=Severity.CRITICAL,
            status=AlertStatus.OPEN,
            trigger=f"{label} conflicts with stated exclusion",
            why="This holding contradicts a red line extracted from your client notes",
            suggested_action="Review for swap to a compatible same-sector replacement (see swap proposals)",
            confidence=1.0,
            evidence=[{
                "isin": position.isin,
                "valor": position.valor,
                "issuer": position.issuer,
                "security": position.security,
                "current_chf": float(position.current_chf) if position.current_chf else None,
                "conflicts": enriched.conflicts,
            }],
        ))
        emitted_keys.append(("dna_conflict", dedup_key))
        count += 1

    return count


async def _generate_values_drift_alert(
    session: AsyncSession,
    client: Client,
    emitted_keys: list[tuple[str, str]],
) -> int:
    """Emit one values_drift alert if portfolio mean fit score is below threshold."""
    mean_fit = await session.scalar(
        select(func.avg(EnrichedHolding.fit_score))
        .join(Position, Position.id == EnrichedHolding.position_id)
        .where(
            Position.client_id == client.id,
            EnrichedHolding.fit_score.isnot(None),
        )
    )

    if mean_fit is None:
        return 0

    mean_fit = float(mean_fit)
    if mean_fit >= VALUES_DRIFT_THRESHOLD:
        return 0

    n_total = await session.scalar(
        select(func.count())
        .select_from(EnrichedHolding)
        .join(Position, Position.id == EnrichedHolding.position_id)
        .where(
            Position.client_id == client.id,
            EnrichedHolding.fit_score.isnot(None),
        )
    ) or 0

    n_below = await session.scalar(
        select(func.count())
        .select_from(EnrichedHolding)
        .join(Position, Position.id == EnrichedHolding.position_id)
        .where(
            Position.client_id == client.id,
            EnrichedHolding.fit_score < 1.0,
            EnrichedHolding.fit_score.isnot(None),
        )
    ) or 0

    if n_total < VALUES_DRIFT_MIN_POSITIONS:
        return 0

    if await should_suppress(client.id, "values_drift", "portfolio"):
        return 0

    session.add(Alert(
        client_id=client.id,
        alert_class="values_drift",
        action_type=ActionType.ACKNOWLEDGE,
        severity=Severity.FYI,
        status=AlertStatus.OPEN,
        trigger=f"Portfolio mean fit score {mean_fit:.2f} — values alignment below target",
        why="The current portfolio composition does not fully reflect the client's expressed values and tilts",
        suggested_action="Review holding mix against client DNA to identify alignment opportunities",
        confidence=0.8,
        evidence=[{
            "mean_fit_score": round(mean_fit, 4),
            "positions_below_baseline": int(n_below),
            "total_positions": int(n_total),
        }],
    ))
    emitted_keys.append(("values_drift", "portfolio"))
    return 1


async def _generate_quiet_client_alert(
    session: AsyncSession,
    client: Client,
    emitted_keys: list[tuple[str, str]],
) -> int:
    """Alert when the last meaningful CRM contact exceeds QUIET_DAYS."""
    last_contact = await session.scalar(
        select(func.max(Interaction.date)).where(Interaction.client_id == client.id)
    )

    today = date.today()
    if last_contact is None:
        days_since = None
        severity = Severity.ATTENTION
    else:
        days_since = (today - last_contact).days
        if days_since < QUIET_DAYS:
            return 0
        severity = Severity.CRITICAL if days_since > QUIET_CRITICAL_DAYS else Severity.ATTENTION

    if await should_suppress(client.id, "quiet_client", "contact"):
        return 0

    trigger = (
        f"Last meaningful contact {days_since}d ago"
        if days_since is not None
        else "No recorded contact in CRM"
    )
    session.add(Alert(
        client_id=client.id,
        alert_class="quiet_client",
        action_type=ActionType.REACH_OUT,
        severity=severity,
        status=AlertStatus.OPEN,
        trigger=trigger,
        why="Client has not been contacted recently — relationship health at risk",
        suggested_action="Proactively reach out; review open promises and upcoming opportunities before contact",
        confidence=1.0,
        evidence=[{
            "last_contact_date": str(last_contact) if last_contact else None,
            "days_since": days_since,
            "quiet_threshold_days": QUIET_DAYS,
        }],
    ))
    emitted_keys.append(("quiet_client", "contact"))
    return 1


async def _generate_promise_alerts(
    session: AsyncSession,
    client: Client,
    dna: ClientDNA,
    emitted_keys: list[tuple[str, str]],
) -> int:
    """Emit one overdue_promise alert per open promise in ClientDNA.promises."""
    promises = dna.promises or []
    if not promises:
        return 0

    # In-run dedup: dna.promises can hold duplicate entries (the LLM re-extracts the
    # same commitment across the 3-year note history, and apply_dna_delta appends over
    # time). The Redis cooldown is only recorded after commit, so without a per-run
    # guard each duplicate would emit its own identical alert row (EPIC-08 AL5).
    seen: set[str] = set()
    count = 0
    for promise in promises:
        text = promise.get("value") or promise.get("text") or ""
        if not text:
            continue
        dedup_key = text[:64]
        if dedup_key in seen:
            continue
        if await should_suppress(client.id, "overdue_promise", dedup_key):
            continue
        seen.add(dedup_key)
        session.add(Alert(
            client_id=client.id,
            alert_class="overdue_promise",
            action_type=ActionType.REACH_OUT,
            severity=Severity.ATTENTION,
            status=AlertStatus.OPEN,
            trigger=f"Open promise: {text}",
            why="An outstanding commitment was extracted from CRM notes and has not been marked complete",
            suggested_action="Review the promise and either fulfil it or update the client on progress",
            confidence=float(promise.get("confidence", 0.7)),
            evidence=[{
                "promise": text,
                "source_note": promise.get("source"),
                "confidence": promise.get("confidence"),
            }],
        ))
        emitted_keys.append(("overdue_promise", dedup_key))
        count += 1

    return count


async def _generate_guardrail_alerts(
    session: AsyncSession,
    client: Client,
    dna: ClientDNA,
    cio_by_isin: dict[str, CIORecommendation],
    emitted_keys: list[tuple[str, str]],
) -> int:
    """Flag swap candidates whose tags conflict with the client's stated exclusions."""
    exclusion_tags: frozenset[str] = frozenset(
        item["tag"] for item in (dna.exclusions or []) if item.get("tag")
    )
    if not exclusion_tags or not cio_by_isin:
        return 0

    proposals = (
        await session.execute(
            select(SwapProposal, Position)
            .join(Position, Position.id == SwapProposal.holding_id)
            .where(Position.client_id == client.id)
        )
    ).all()

    if not proposals:
        return 0

    seen_candidates: set[str] = set()
    count = 0

    for proposal, position in proposals:
        candidate_isin = proposal.candidate_isin
        if not candidate_isin or candidate_isin in seen_candidates:
            continue

        cio_row = cio_by_isin.get(candidate_isin)
        if cio_row is None:
            continue

        candidate_value_tags = frozenset(cio_row.tags.get("value_tags", []))
        conflicting = exclusion_tags & candidate_value_tags
        if not conflicting:
            continue

        if candidate_isin in seen_candidates:
            continue

        if await should_suppress(client.id, "behavioural_guardrail", candidate_isin):
            continue

        seen_candidates.add(candidate_isin)
        label = cio_row.isin or candidate_isin
        session.add(Alert(
            client_id=client.id,
            alert_class="behavioural_guardrail",
            action_type=ActionType.ACKNOWLEDGE,
            severity=Severity.ATTENTION,
            status=AlertStatus.OPEN,
            trigger=f"Proposed replacement {label} may conflict with stated red lines",
            why="A CIO-suggested swap candidate shares tags with the client's stated exclusions",
            suggested_action="Verify candidate alignment with client DNA before presenting to client",
            confidence=0.9,
            evidence=[{
                "candidate_isin": candidate_isin,
                "conflicting_tags": sorted(conflicting),
                "client_exclusions": sorted(exclusion_tags),
                "candidate_value_tags": sorted(candidate_value_tags),
                "position_isin": position.isin,
                "position_issuer": position.issuer,
            }],
        ))
        emitted_keys.append(("behavioural_guardrail", candidate_isin))
        count += 1

    return count
