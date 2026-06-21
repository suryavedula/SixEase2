"""Book-wide Change Radar builder (TASK-059, EPIC-08).

The event-centric *inversion* of the per-client Alert / NewsItem pipeline. Every
signal — news, CIO SELL flip, drift breach, DNA conflict, relationship event —
reduces to one triggering *entity* (instrument / sector / client / macro), fans
out to every impacted client by database-wide exposure, and is scored by

    impact = Σ_clients(exposure_chf × magnitude × dna_relevance) × recency

Materialises change_events (delete-and-reload, idempotent) from current Alert and
NewsItem state. Run AFTER seed/alerts + seed/drift + scan/news so all signals exist.
Reuses the existing alert rows — it never recomputes drift / sells / news (E:AC).

Grounding (G2): every CHF figure comes from Position rows; nothing is authored here.
No-fallbacks: an entity that resolves to zero impacted clients is still written with
unresolved_reason set — surfaced explicitly, never silently dropped.

Call from POST /admin/seed/radar.
"""

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models.derived import Alert, ChangeEvent, NewsItem, SwapProposal
from app.models.source import Client, Position

log = get_logger(__name__)

# Recency half-life: an event's aggregate weight halves every N days (tunable, TASK-058).
RECENCY_HALF_LIFE_DAYS: float = 14.0

# Per-signal magnitude base by severity band (independent of alert_rank's weights).
_SEVERITY_MAGNITUDE: dict[str, float] = {
    "Critical": 1.0,
    "Attention": 0.6,
    "FYI": 0.3,
}

# Classes rooted in the client's stated DNA weigh more in per-client relevance.
_DNA_RELEVANT_CLASSES: frozenset[str] = frozenset(
    {"dna_conflict", "behavioural_guardrail", "panic", "good_news"}
)

# News alert classes — these events are driven from NewsItem rows, not re-derived
# from their alerts (the NewsItem already carries the cross-client fan-out).
_NEWS_CLASSES: frozenset[str] = frozenset({"news_impact", "good_news", "panic"})

# Human-readable action label per non-news alert class.
_ACTION_LABEL: dict[str, str] = {
    "drift_breach": "Drift breach",
    "stale_sell": "CIO SELL flip",
    "dna_conflict": "DNA conflict",
    "behavioural_guardrail": "Guardrail",
    "values_drift": "Values drift",
    "quiet_client": "Quiet client",
    "overdue_promise": "Overdue promise",
    "price_move": "Price move",
    "maturity_soon": "Bond maturing",
}

# Source channel per alert class.
_SOURCE: dict[str, str] = {
    "drift_breach": "drift",
    "stale_sell": "cio",
    "dna_conflict": "dna",
    "behavioural_guardrail": "dna",
    "values_drift": "dna",
    "quiet_client": "crm",
    "overdue_promise": "crm",
    "price_move": "price",
    "maturity_soon": "price",
}


# ---------------------------------------------------------------------------
# Pure helpers (no DB) — unit-testable in isolation
# ---------------------------------------------------------------------------


@dataclass
class RadarSignal:
    """One client's exposure to one entity, normalised from an Alert or NewsItem."""

    entity_key: str
    entity_type: str  # instrument | sector | client | macro
    entity_label: str | None
    action: str
    source: str
    client_id: str
    magnitude: float
    dna_relevance: float
    event_ts: datetime | None
    isins: list[str] = field(default_factory=list)  # instruments to price the client's exposure
    sub_asset_class: str | None = None
    drift_caused: float | None = None
    dna_note: str | None = None
    suggested_action: str | None = None
    alert_id: str | None = None
    news_url: str | None = None  # article URL for news signals


def signal_magnitude(severity_value: str | None, confidence: float | None) -> float:
    """Normalised event magnitude from severity band × confidence (0..1)."""
    base = _SEVERITY_MAGNITUDE.get(severity_value or "", 0.3)
    conf = confidence if confidence is not None else 0.7
    return base * conf


def dna_relevance(alert_class: str | None) -> float:
    """Per-client relevance multiplier — DNA-rooted classes count more."""
    return 1.5 if (alert_class or "") in _DNA_RELEVANT_CLASSES else 1.0


def recency_decay(event_ts: datetime | None, now: datetime, half_life_days: float = RECENCY_HALF_LIFE_DAYS) -> float:
    """Exponential decay on event age; 0.5 for unknown timestamps."""
    if event_ts is None:
        return 0.5
    age_days = (now - event_ts).total_seconds() / 86_400.0
    if age_days <= 0:
        return 1.0
    return 0.5 ** (age_days / half_life_days)


def score_event(
    contributions: list[tuple[float, float, float]],
    latest_ts: datetime | None,
    now: datetime,
) -> float:
    """Aggregate impact = Σ_clients(exposure_chf × magnitude × dna_relevance) × recency.

    `contributions` is a list of (exposure_chf, magnitude, dna_relevance) tuples,
    one per impacted client. Pure — `now` is injected so tests are deterministic.
    """
    base = sum(exp * mag * dna for exp, mag, dna in contributions)
    return base * recency_decay(latest_ts, now)


def extract_alert_entity(alert: Alert) -> tuple[str, str, str | None, str | None] | None:
    """Map a non-news alert to (entity_type, entity_key, entity_label, exposure_hint).

    exposure_hint is the isin (instrument) or sub_asset_class (sector); None for
    client/macro entities (which price against the whole portfolio). Returns None
    when no entity can be extracted — the caller surfaces it as unresolved.
    """
    cls = alert.alert_class or ""
    ev = (alert.evidence or [{}])[0] if alert.evidence else {}

    if cls == "drift_breach":
        sac = ev.get("sub_asset_class")
        if not sac:
            return None
        return ("sector", f"sac:{sac}", sac, sac)

    if cls in ("stale_sell", "dna_conflict", "price_move", "maturity_soon"):
        isin = ev.get("isin")
        if not isin:
            return None
        label = ev.get("issuer") or ev.get("security") or isin
        return ("instrument", f"isin:{isin}", label, isin)

    if cls == "behavioural_guardrail":
        isin = ev.get("candidate_isin")
        if not isin:
            return None
        return ("instrument", f"isin:{isin}", isin, isin)

    if cls in ("values_drift", "quiet_client", "overdue_promise"):
        return ("client", f"client:{alert.client_id}", None, None)

    return None


# ---------------------------------------------------------------------------
# Async orchestrator
# ---------------------------------------------------------------------------


async def build_change_radar(
    session: AsyncSession,
    extra_signals: list[RadarSignal] | None = None,
) -> dict[str, int]:
    """Rebuild the change_events table from current Alert + NewsItem state.

    Idempotent: wipes change_events, then materialises one row per triggering
    entity with its impacted-client fan-out and aggregate impact score.
    Returns {"events_written": N, "unresolved": M}.

    `extra_signals` are pre-built signals from channels that have no per-client
    Alert/NewsItem rows of their own — notably email (TASK-060). They are merged
    into the same `entity_key` grouping, so an email on an instrument auto-dedups
    with a drift/CIO/news event on the same instrument (cross-channel dedup, E:AC).
    """
    now = datetime.now(timezone.utc)

    # Idempotency: full rebuild — the radar is a pure projection of live signals.
    # Demo events (entity_key "email:demo:%") are pinned: written directly by
    # loaders/demo_email.py and preserved across rebuilds so the pitch scenario
    # survives the refresh loop.
    await session.execute(
        delete(ChangeEvent).where(
            (ChangeEvent.entity_key.is_(None))
            | (ChangeEvent.entity_key.notlike("email:demo:%"))
        )
    )

    # --- Preload exposure/context tables once (book is small: 4 personas) ---
    clients = (await session.execute(select(Client))).scalars().all()
    client_name: dict[str, str] = {str(c.id): c.name for c in clients}

    positions = (await session.execute(select(Position))).scalars().all()
    client_total_chf: dict[str, float] = defaultdict(float)
    for p in positions:
        if p.current_chf is not None:
            client_total_chf[str(p.client_id)] += float(p.current_chf)

    # Best swap per (client_id, held isin) for the one-click fix on instrument events.
    swap_rows = (
        await session.execute(
            select(SwapProposal, Position)
            .join(Position, Position.id == SwapProposal.holding_id)
            .where(SwapProposal.candidate_isin.isnot(None))
        )
    ).all()
    swap_lookup: dict[tuple[str, str], dict] = {}
    for proposal, pos in swap_rows:
        if not pos.isin:
            continue
        key = (str(pos.client_id), pos.isin)
        prev = swap_lookup.get(key)
        gain = proposal.fit_gain or 0.0
        if prev is None or gain > (prev.get("fit_gain") or 0.0):
            swap_lookup[key] = {
                "candidate_isin": proposal.candidate_isin,
                "candidate_valor": proposal.candidate_valor,
                "fit_gain": proposal.fit_gain,
                "dna_reason": proposal.dna_reason,
            }

    # --- Build per-client signals from both sources ---
    alerts = (
        await session.execute(select(Alert).where(Alert.status == "open"))
    ).scalars().all()

    # Seed with externally-built signals (email, TASK-060); Alert/NewsItem append below.
    signals: list[RadarSignal] = list(extra_signals or [])
    unresolved_rows: list[ChangeEvent] = []

    # News alerts keyed by (client_id, url) so a NewsItem can attach the client's
    # suggested action + alert_id for one-click convert downstream.
    news_alert_by_client_url: dict[tuple[str, str], Alert] = {}
    for a in alerts:
        if (a.alert_class or "") in _NEWS_CLASSES:
            ev = (a.evidence or [{}])[0] if a.evidence else {}
            url = ev.get("url")
            if url:
                key = (str(a.client_id), url)
                # Prefer the higher-severity alert for the same article.
                prev = news_alert_by_client_url.get(key)
                if prev is None or _SEVERITY_MAGNITUDE.get(
                    a.severity.value if hasattr(a.severity, "value") else str(a.severity), 0
                ) > _SEVERITY_MAGNITUDE.get(
                    prev.severity.value if hasattr(prev.severity, "value") else str(prev.severity), 0
                ):
                    news_alert_by_client_url[key] = a

    # 1) Non-news alerts → signals grouped by extracted entity.
    for a in alerts:
        cls = a.alert_class or ""
        if cls in _NEWS_CLASSES:
            continue
        ent = extract_alert_entity(a)
        if ent is None:
            unresolved_rows.append(
                ChangeEvent(
                    action=_ACTION_LABEL.get(cls, cls),
                    entity_key=None,
                    entity_type=None,
                    entity_label=a.trigger,
                    source=_SOURCE.get(cls, "alert"),
                    event_ts=a.created_at,
                    client_count=0,
                    unresolved_reason=f"No entity extractable from {cls} alert {a.id}",
                    sources=[{"type": cls, "alert_id": str(a.id)}],
                )
            )
            continue
        entity_type, entity_key, entity_label, hint = ent
        sev = a.severity.value if hasattr(a.severity, "value") else str(a.severity)
        ev = (a.evidence or [{}])[0] if a.evidence else {}
        signals.append(
            RadarSignal(
                entity_key=entity_key,
                entity_type=entity_type,
                entity_label=entity_label,
                action=_ACTION_LABEL.get(cls, cls),
                source=_SOURCE.get(cls, "alert"),
                client_id=str(a.client_id),
                magnitude=signal_magnitude(sev, a.confidence),
                dna_relevance=dna_relevance(cls),
                event_ts=a.created_at,
                isins=[hint] if entity_type == "instrument" and hint else [],
                sub_asset_class=hint if entity_type == "sector" else None,
                drift_caused=ev.get("drift_pp") if cls == "drift_breach" else None,
                dna_note=a.why,
                suggested_action=a.suggested_action,
                alert_id=str(a.id),
            )
        )

    # 2) NewsItem rows → one event per article, fanned out across client_ids.
    news_rows = (await session.execute(select(NewsItem))).scalars().all()
    for item in news_rows:
        client_ids = item.client_ids or []
        if not client_ids:
            continue
        # Syndicated copies of one story (e.g. in./uk./za.investing.com) get distinct
        # ER cluster ids and URLs but share a headline — group on the normalised
        # headline so they collapse into a single radar event, not N near-duplicates.
        headline_key = " ".join((item.headline or "").lower().split())
        cluster = headline_key or item.event_cluster_id or item.url or str(item.id)
        isins = [h.get("isin") for h in (item.matched_holdings or []) if h.get("isin")]
        entity_type = "instrument" if isins else "macro"
        sentiment = abs(item.sentiment or 0.0)
        for client_id in client_ids:
            matched = news_alert_by_client_url.get((client_id, item.url or ""))
            cls = (matched.alert_class if matched else None) or "news_impact"
            sev = (
                (matched.severity.value if hasattr(matched.severity, "value") else str(matched.severity))
                if matched
                else "Attention"
            )
            base = _SEVERITY_MAGNITUDE.get(sev, 0.6)
            signals.append(
                RadarSignal(
                    entity_key=f"news:{cluster}",
                    entity_type=entity_type,
                    entity_label=item.headline,
                    action="News threat" if item.impact == "threat" else "News",
                    source="news",
                    client_id=client_id,
                    magnitude=base * (0.5 + 0.5 * sentiment),
                    dna_relevance=dna_relevance(cls),
                    event_ts=item.published_at,
                    isins=isins,
                    dna_note=(matched.why if matched else None),
                    suggested_action=(matched.suggested_action if matched else None),
                    alert_id=(str(matched.id) if matched else None),
                    news_url=item.url,
                )
            )

    # --- Group signals by entity, resolve exposure, score ---
    grouped: dict[str, list[RadarSignal]] = defaultdict(list)
    for s in signals:
        grouped[s.entity_key].append(s)

    events_written = 0
    zero_exposure = 0
    for entity_key, group in grouped.items():
        head = group[0]

        # One contribution per client (best signal if a client appears twice).
        by_client: dict[str, RadarSignal] = {}
        for s in group:
            prev = by_client.get(s.client_id)
            if prev is None or s.magnitude > prev.magnitude:
                by_client[s.client_id] = s

        impacted: list[dict] = []
        contributions: list[tuple[float, float, float]] = []
        total_exposure = 0.0
        timestamps: list[datetime] = []

        for client_id, s in by_client.items():
            exposure = _client_exposure(s, positions, client_total_chf, client_id)
            total = client_total_chf.get(client_id, 0.0)
            pct = (exposure / total * 100.0) if total > 0 else None

            swap = None
            if s.entity_type == "instrument":
                for isin in s.isins:
                    swap = swap_lookup.get((client_id, isin))
                    if swap:
                        break

            impacted.append(
                {
                    "client_id": client_id,
                    "client_name": client_name.get(client_id, client_id),
                    "exposure_chf": round(exposure, 2),
                    "exposure_pct": round(pct, 2) if pct is not None else None,
                    "drift_caused": s.drift_caused,
                    "dna_note": s.dna_note,
                    "suggested_action": s.suggested_action,
                    "alert_id": s.alert_id,
                    "swap_candidate": swap,
                }
            )
            contributions.append((exposure, s.magnitude, s.dna_relevance))
            total_exposure += exposure
            if s.event_ts is not None:
                timestamps.append(s.event_ts)

        latest_ts = max(timestamps) if timestamps else None
        impact = score_event(contributions, latest_ts, now)
        client_count = len(impacted)
        # Rank impacted clients by their own contribution (biggest exposure first).
        impacted.sort(key=lambda c: c["exposure_chf"], reverse=True)

        unresolved_reason = None
        if total_exposure <= 0:
            unresolved_reason = (
                f"Entity {entity_key} matched {client_count} client(s) but resolved to zero CHF exposure"
            )
            zero_exposure += 1

        batch_action = None
        if client_count > 1:
            batch_action = (
                f"{head.action} affects {client_count} clients — review and batch-apply per client"
            )

        session.add(
            ChangeEvent(
                action=head.action,
                entity_key=entity_key,
                entity_type=head.entity_type,
                entity_label=head.entity_label,
                source=head.source,
                event_ts=latest_ts,
                magnitude=max((s.magnitude for s in by_client.values()), default=None),
                impact_score=impact,
                client_count=client_count,
                total_exposure_chf=round(total_exposure, 2),
                impacted_clients=impacted,
                suggested_batch_action=batch_action,
                sources=[{
                    "type": head.source,
                    "entity": entity_key,
                    "signals": client_count,
                    **({"url": head.news_url} if head.source == "news" and head.news_url else {}),
                }],
                unresolved_reason=unresolved_reason,
            )
        )
        events_written += 1

    for row in unresolved_rows:
        session.add(row)

    await session.commit()

    # Unresolved = entity-less alerts + grouped events that resolved to zero exposure.
    unresolved_total = len(unresolved_rows) + zero_exposure
    events_written += len(unresolved_rows)
    log.info(
        "radar.build_complete",
        events_written=events_written,
        unresolved=unresolved_total,
        clients=len(clients),
    )
    return {"events_written": events_written, "unresolved": unresolved_total}


def _client_exposure(
    signal: RadarSignal,
    positions: list[Position],
    client_total_chf: dict[str, float],
    client_id: str,
) -> float:
    """Resolve a client's CHF exposure to a signal's entity from Position rows (G2)."""
    if signal.entity_type == "instrument":
        isins = set(signal.isins)
        return sum(
            float(p.current_chf)
            for p in positions
            if str(p.client_id) == client_id and p.isin in isins and p.current_chf is not None
        )
    if signal.entity_type == "sector":
        return sum(
            float(p.current_chf)
            for p in positions
            if str(p.client_id) == client_id
            and p.sub_asset_class == signal.sub_asset_class
            and p.current_chf is not None
        )
    # client / macro — price against the whole portfolio
    return client_total_chf.get(client_id, 0.0)
