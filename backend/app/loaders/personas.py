"""Full end-to-end persona seeding pipeline (TASK-055, EPIC-14).

Runs the complete pipeline for the four real personas: Räber, Schneider, Huber,
Ammann. All individual loaders are called in dependency order so the demo works
offline — SIX pricing falls back gracefully, trigger articles are seeded, and
the LLM is local Ollama.

D3 scripted triggers (step 10) produce one seeded NewsItem per persona so
news_impact / good_news alerts fire without live Event Registry coverage.

Call from POST /admin/seed/personas.
"""

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.loaders.alert_rank import rank_alerts
from app.loaders.alerts import generate_alerts
from app.loaders.change_radar import build_change_radar
from app.loaders.crm import load_crm
from app.loaders.drift import compute_drift
from app.loaders.dna import extract_dna
from app.loaders.email_ingest import ingest_email_signals
from app.loaders.fact_sheet import assemble_fact_sheet
from app.loaders.fit import compute_fit
from app.loaders.holdings import enrich_holdings
from app.loaders.message_render import render_message_draft
from app.loaders.news_match import fanout_seeded_news
from app.loaders.news_seed import seed_news_triggers
from app.loaders.portfolio import load_portfolio
from app.loaders.style_profile import extract_style_profiles
from app.loaders.swap import compute_swaps
from app.loaders.tags import load_tags
from app.loaders.watchlist import build_watchlists
from app.logging import get_logger
from app.models.source import Client

log = get_logger(__name__)

# Canonical names — must match crm.py _PERSONA_SHEETS exactly.
REAL_PERSONA_NAMES: tuple[str, ...] = (
    "Eugen Räber",
    "Hubertus Schneider",
    "Marius Huber",
    "Julian Ammann",
)


async def seed_personas(session: AsyncSession, data_dir: str | Path) -> dict:
    """Run the full pipeline for the four real personas end-to-end.

    All steps are idempotent — safe to call multiple times. Steps 4–5 and 14
    call the local Ollama LLM; all other steps are fully offline.

    Steps:
      1  portfolio   — positions, strategies, CIO list, sample clients
      2  crm         — real persona clients + interaction notes
      3  tags        — instrument value tags (enriched_holdings + CIO rows)
      4  dna         — LLM extraction; skips clients without interactions
      5  style       — LLM communication style profiles; skips without interactions
      6  fit         — DNA-vs-tag fit scores; skips without DNA
      7  swap        — DNA-conflict swap candidates; skips without DNA
      8  enrich      — live SIX pricing with graceful fallback
      9  watchlist   — per-client entity + theme watchlist; skips without DNA
     10  news        — four scripted D3 offline trigger articles
     10b news_fanout — fan seeded articles out to all holders (multi-client events)
     11  alerts      — eight non-drift alert classes
     12  drift       — drift_breach + stale_sell alerts
     13  rank        — rank_score for all open alerts
     13b email       — inbound Microsoft Graph email → radar signals (no-op if unset)
     14  radar       — book-wide Change Radar (event-inversion + impact scoring)
     15  message     — per-persona fact sheet + LLM draft (best-effort)

    Returns a summary dict with row counts for every step and per-persona
    message results from step 14.
    """
    log.info("personas.pipeline_start")
    summary: dict = {}

    summary["portfolio"] = await load_portfolio(session, data_dir)
    log.info("personas.step_done", step="portfolio")

    summary["crm"] = await load_crm(session, data_dir)
    log.info("personas.step_done", step="crm")

    summary["tags"] = await load_tags(session)
    log.info("personas.step_done", step="tags")

    summary["dna"] = await extract_dna(session)
    log.info("personas.step_done", step="dna")

    summary["style_profile"] = await extract_style_profiles(session)
    log.info("personas.step_done", step="style_profile")

    summary["fit"] = await compute_fit(session)
    log.info("personas.step_done", step="fit")

    summary["swap"] = await compute_swaps(session)
    log.info("personas.step_done", step="swap")

    summary["enrich"] = await enrich_holdings(session)
    log.info("personas.step_done", step="enrich")

    summary["watchlist"] = await build_watchlists(session)
    log.info("personas.step_done", step="watchlist")

    summary["news"] = await seed_news_triggers(session)
    log.info("personas.step_done", step="news")

    # Fan the seeded triggers out to every holder of the named instruments, so a story
    # on a widely-held name becomes a multi-client radar event (and news_impact alerts
    # fire for each holder below). Without this, seeded NewsItems carry no client_ids.
    summary["news_fanout"] = await fanout_seeded_news(session)
    log.info("personas.step_done", step="news_fanout")

    summary["alerts"] = await generate_alerts(session)
    log.info("personas.step_done", step="alerts")

    summary["drift"] = await compute_drift(session)
    log.info("personas.step_done", step="drift")

    summary["rank"] = await rank_alerts(session)
    log.info("personas.step_done", step="rank")

    # Step 13b: inbound email signals via Microsoft Graph (TASK-060). Empty list when
    # MS_GRAPH_* is unset, so the offline demo is unaffected; folded into the radar below.
    email_signals = await ingest_email_signals(session)
    summary["email_ingest"] = {"signals": len(email_signals)}
    log.info("personas.step_done", step="email_ingest")

    # Step 14: book-wide Change Radar — must run after alerts + drift + rank so all
    # signals exist to invert into event-centric change_events (TASK-059). Email signals
    # merge by entity_key so an email on an instrument dedups with its drift/CIO/news event.
    summary["radar"] = await build_change_radar(session, extra_signals=email_signals)
    log.info("personas.step_done", step="radar")

    # Step 15: per-persona fact sheet + LLM draft.
    # Best-effort: skips if no dna_conflict alert exists for a persona.
    messages: dict[str, dict] = {}
    for name in REAL_PERSONA_NAMES:
        client = await session.scalar(select(Client).where(Client.name == name))
        if client is None:
            log.warning("personas.client_not_found_for_message", name=name)
            messages[name] = {"skipped": "client not found after crm seed"}
            continue
        try:
            fact_result = await assemble_fact_sheet(session, client.id)
            draft_id = uuid.UUID(fact_result["draft_id"])
            render_result = await render_message_draft(session, draft_id)
            messages[name] = {
                "draft_id": str(draft_id),
                "preset": render_result.get("preset"),
                "guardrail_passed": render_result.get("guardrail_passed", True),
            }
            log.info("personas.message_rendered", name=name, draft_id=str(draft_id))
        except RuntimeError as exc:
            log.warning("personas.message_skipped", name=name, reason=str(exc))
            messages[name] = {"skipped": str(exc)}
        except Exception as exc:
            log.error("personas.message_failed", name=name, error=str(exc))
            messages[name] = {"error": str(exc)}

    summary["messages"] = messages
    log.info("personas.pipeline_complete")
    return summary
