"""Proactive radar dispatch loop (EPIC-08 — push, not pull).

Turns the materialised Change Radar from pull-only into push. Each cycle it reads
resolved change_events and:

  • Critical changes (aggregate magnitude ≥ threshold) → near-real-time push:
    in-app SSE always, plus an RM email (deferred during quiet hours). Deduped via
    the radar_deliveries ledger; re-notified only when impact climbs materially.
  • Everything else → a once-daily digest email at radar_digest_hour.

RM-only delivery — nothing here reaches a client (autonomy boundary G1, §3). The
radar itself stays zero-LLM; this loop spends no hosted-LLM budget either.

Usage (from main.py lifespan):
    task = start_radar_dispatch()       # startup
    await stop_radar_dispatch(task)     # shutdown
"""

import asyncio
import contextlib
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app import notify, radar_stream
from app.config import get_settings
from app.db import SessionFactory
from app.logging import get_logger
from app.models.derived import ChangeEvent, RadarDelivery

settings = get_settings()
log = get_logger(__name__)


# ---------------------------------------------------------------------------
# Pure helpers (unit-testable)
# ---------------------------------------------------------------------------


def is_quiet_hour(hour: int, start: int, end: int) -> bool:
    """True if `hour` falls in the quiet window [start, end). Wrap-around aware.

    start == end means "no quiet hours". e.g. start=22, end=7 → quiet 22:00–06:59.
    """
    if start == end:
        return False
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end  # wraps past midnight


def _event_payload(row: ChangeEvent) -> dict:
    """Compact SSE payload for a pushed change (browser refetches /radar for detail)."""
    return {
        "type": "change",
        "id": str(row.id),
        "entity_key": row.entity_key,
        "action": row.action,
        "entity_label": row.entity_label,
        "source": row.source,
        "magnitude": row.magnitude,
        "impact_score": row.impact_score,
        "client_count": row.client_count,
        "total_exposure_chf": (
            float(row.total_exposure_chf) if row.total_exposure_chf is not None else None
        ),
    }


def _critical_email_html(row: ChangeEvent) -> str:
    names = ", ".join(
        c.get("client_name", "?") for c in (row.impacted_clients or [])[:8]
    ) or "—"
    exposure = (
        f"CHF {float(row.total_exposure_chf):,.0f}"
        if row.total_exposure_chf is not None
        else "—"
    )
    return (
        f"<h2>⚠️ {row.action}: {row.entity_label or row.entity_key}</h2>"
        f"<p><b>Source:</b> {row.source} &nbsp; <b>Clients affected:</b> "
        f"{row.client_count} &nbsp; <b>Total exposure:</b> {exposure}</p>"
        f"<p><b>Impacted:</b> {names}</p>"
        f"<p>Open the SixEase Action Center to review evidence and act. "
        f"<i>Nothing has been sent to any client — this is for your review.</i></p>"
    )


def _digest_email_html(rows: list[ChangeEvent]) -> str:
    items = "".join(
        f"<li><b>{r.action}</b>: {r.entity_label or r.entity_key} "
        f"({r.client_count} client(s), "
        f"{'CHF %0.0f' % float(r.total_exposure_chf) if r.total_exposure_chf is not None else '—'})"
        f"</li>"
        for r in rows
    )
    return (
        f"<h2>SixEase daily radar digest</h2>"
        f"<p>{len(rows)} change(s) for your review:</p>"
        f"<ul>{items}</ul>"
        f"<p><i>For your review only — nothing has been sent to any client.</i></p>"
    )


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


async def _last_delivery(session: AsyncSession, entity_key: str) -> RadarDelivery | None:
    return (
        await session.execute(
            select(RadarDelivery)
            .where(RadarDelivery.entity_key == entity_key)
            .order_by(RadarDelivery.delivered_at.desc())
            .limit(1)
        )
    ).scalars().first()


async def run_dispatch_cycle(session: AsyncSession, now: datetime) -> dict[str, int]:
    """One dispatch pass. `now` is injected so tests are deterministic.

    Returns {"critical_pushed", "emails_sent", "digest_sent"}.
    """
    resolved = list(
        (
            await session.execute(
                select(ChangeEvent)
                .where(
                    ChangeEvent.client_count > 0,
                    ChangeEvent.unresolved_reason.is_(None),
                )
                .order_by(ChangeEvent.impact_score.desc().nullslast())
            )
        ).scalars().all()
    )

    quiet = is_quiet_hour(now.hour, settings.radar_quiet_start, settings.radar_quiet_end)
    margin = settings.radar_rebroadcast_margin

    critical_pushed = emails_sent = 0
    non_critical: list[ChangeEvent] = []

    for row in resolved:
        mag = row.magnitude or 0.0
        if mag < settings.radar_critical_magnitude:
            non_critical.append(row)
            continue
        if not row.entity_key:
            continue

        last = await _last_delivery(session, row.entity_key)
        if last is not None:
            prev = last.impact_at_delivery or 0.0
            if (row.impact_score or 0.0) <= prev * (1 + margin):
                continue  # already delivered; impact hasn't climbed materially

        # SSE always fires; the email is deferred during quiet hours.
        radar_stream.publish(_event_payload(row))
        channel = "sse"
        if not quiet:
            if await notify.send_rm_email(
                f"⚠️ {row.action}: {row.entity_label or row.entity_key}",
                _critical_email_html(row),
            ):
                channel = "email"
                emails_sent += 1

        session.add(
            RadarDelivery(
                entity_key=row.entity_key,
                channel=channel,
                impact_at_delivery=row.impact_score,
            )
        )
        critical_pushed += 1

    # Daily digest — once per UTC day, at/after the configured hour.
    digest_sent = 0
    digest_key = f"digest:{now.strftime('%Y-%m-%d')}"
    if non_critical and now.hour >= settings.radar_digest_hour:
        if await _last_delivery(session, digest_key) is None:
            top = non_critical[: settings.radar_digest_limit]
            if await notify.send_rm_email(
                f"SixEase daily digest — {len(non_critical)} change(s)",
                _digest_email_html(top),
            ):
                digest_sent = 1
            # Record regardless of send success so we don't retry all day on a
            # mail outage; the changes remain visible in the pull radar.
            session.add(RadarDelivery(entity_key=digest_key, channel="digest"))

    await session.commit()
    return {
        "critical_pushed": critical_pushed,
        "emails_sent": emails_sent,
        "digest_sent": digest_sent,
    }


async def run_radar_dispatch() -> None:
    """Infinite loop: dispatch pending radar changes, then sleep one interval."""
    if not settings.radar_dispatch_enabled:
        log.info("radar_dispatch.disabled", reason="radar_dispatch_enabled is false")
        return

    log.info(
        "radar_dispatch.started",
        interval=settings.radar_dispatch_interval,
        critical_magnitude=settings.radar_critical_magnitude,
        smtp=notify.smtp_enabled(),
    )
    while True:
        try:
            async with SessionFactory() as session:
                counts = await run_dispatch_cycle(session, datetime.now(timezone.utc))
            if counts["critical_pushed"] or counts["digest_sent"]:
                log.info("radar_dispatch.cycle", **counts)
        except asyncio.CancelledError:
            raise
        except Exception as exc:  # noqa: BLE001
            log.warning("radar_dispatch.cycle_error", error=str(exc))

        await asyncio.sleep(settings.radar_dispatch_interval)


def start_radar_dispatch() -> "asyncio.Task[None]":
    """Spawn the dispatch loop as a named asyncio background task."""
    return asyncio.create_task(run_radar_dispatch(), name="radar-dispatch")


async def stop_radar_dispatch(task: "asyncio.Task[None]") -> None:
    """Cancel the dispatch loop and wait for it to finish."""
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    log.info("radar_dispatch.stopped")
