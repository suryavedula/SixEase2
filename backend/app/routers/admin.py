"""Admin / seed endpoints (EPIC-02).

One-shot management endpoints for loading the provided workbooks into the DB.
All seed operations are idempotent: safe to call repeatedly without duplicating
data. These endpoints are not guarded by auth in the dev/hackathon build — add
a header check before any production exposure.

Endpoints added by task:
  TASK-009: POST /admin/seed/crm        — CRM interaction notes
  TASK-008: POST /admin/seed/portfolio  — mandate strategies, CIO list, positions
  TASK-010: POST /admin/seed/tags       — instrument value tags (enriched_holdings + CIO)
  TASK-011: POST /admin/seed/synthetic  — 100 synthetic clients for scale proof (G6)
  TASK-015: POST /admin/seed/embeddings — pgvector embeddings for notes + DNA
  TASK-016: POST /admin/seed/dna        — DNA extraction from CRM notes
  TASK-017: POST /admin/seed/style-profile — communication style-profile extraction
  TASK-020: POST /admin/seed/fit        — fit scores (enriched_holdings)
  TASK-021: POST /admin/seed/swap       — DNA-conflict swap candidates (swap_proposals)
  TASK-022: POST /admin/seed/drift      — drift breach + stale-SELL alerts
  TASK-026: POST /admin/seed/enrich     — live SIX pricing + quantity for holdings
  TASK-027: POST /admin/seed/watchlist  — per-client watchlist (entities ∪ DNA themes)
  TASK-028: POST /admin/scan/news       — fetch live news + match to client watchlists
  TASK-030: POST /admin/fanout/news     — inverted-index fan-out + LLM triage (one cycle)
  TASK-031: POST /admin/seed/news       — 4 seeded persona trigger articles (offline demo)
  TASK-032: POST /admin/seed/alerts     — all-signals alert generation (8 non-drift classes)
  TASK-034: POST /admin/seed/rank       — rank_score computation for all open alerts (AL6)
  TASK-059: POST /admin/seed/radar      — book-wide Change Radar (event-inversion + impact)
  TASK-060: POST /admin/ingest/email    — Microsoft Graph email → radar signals (folds into radar)
  TASK-037: POST /admin/assemble/fact-sheet — deterministic MSG2 fact sheet → MessageDraft
  TASK-038: POST /admin/render/message      — MSG3 LLM render + MSG4 guardrail
  TASK-055: POST /admin/seed/personas       — full end-to-end pipeline for 4 real personas
"""

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.loaders.crm import load_crm
from app.loaders.news_fanout import run_fanout
from app.loaders.news_match import fanout_seeded_news, scan_news_all_clients
from app.loaders.holdings import enrich_holdings
from app.loaders.watchlist import build_watchlists
from app.loaders.drift import compute_drift
from app.loaders.swap import compute_swaps
from app.loaders.dna import extract_dna
from app.loaders.fit import compute_fit
from app.loaders.style_profile import extract_style_profiles
from app.loaders.embeddings import seed_dna_embeddings, seed_interaction_embeddings
from app.loaders.portfolio import load_portfolio
from app.loaders.synthetic import load_synthetic_clients
from app.loaders.news_seed import seed_news_triggers
from app.loaders.price_watch import scan_price_signals
from app.loaders.alerts import generate_alerts
from app.loaders.alert_rank import rank_alerts
from app.loaders.change_radar import build_change_radar
from app.loaders.email_ingest import ingest_email_signals
from app.loaders.fact_sheet import assemble_fact_sheet
from app.loaders.message_render import render_message_draft
from app.loaders.personas import seed_personas
from app.loaders.persona_portfolio import link_persona_portfolios
from app.loaders.tags import load_tags
from app.llm import budget_status
from app.logging import get_logger

router = APIRouter(prefix="/admin", tags=["admin"])
log = get_logger(__name__)
settings = get_settings()


@router.post("/seed/crm")
async def seed_crm(session: AsyncSession = Depends(get_session)) -> dict:
    """Load the four persona CRM tabs into clients + interactions tables.

    Idempotent: clients are get-or-created by name; interactions are
    deleted-and-reloaded per client so a re-run reflects workbook edits.
    """
    try:
        counts = await load_crm(session, settings.wealth_data_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Workbook not found: {exc}") from exc
    except Exception as exc:
        log.error("admin.seed_crm_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"status": "ok", "loaded": counts}


@router.post("/seed/portfolio")
async def seed_portfolio(session: AsyncSession = Depends(get_session)) -> dict:
    """Load mandate strategies, CIO recommendations, seed clients, and positions.

    Idempotent: mandate strategies upsert by (mandate, sub_asset_class); seed
    clients are get-or-created by name; positions and CIO rows are
    deleted-and-reloaded. Safe to call multiple times.
    """
    try:
        counts = await load_portfolio(session, settings.wealth_data_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Workbook not found: {exc}") from exc
    except Exception as exc:
        log.error("admin.seed_portfolio_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"status": "ok", "loaded": counts}


@router.post("/seed/tags")
async def seed_tags(session: AsyncSession = Depends(get_session)) -> dict:
    """Annotate all positions (→ enriched_holdings) and CIO rows with region/sector/value tags.

    Requires /admin/seed/portfolio to have run first. Idempotent.
    """
    try:
        counts = await load_tags(session)
    except Exception as exc:
        log.error("admin.seed_tags_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": counts}


@router.post("/seed/synthetic")
async def seed_synthetic(session: AsyncSession = Depends(get_session)) -> dict:
    """Generate 100 seeded synthetic clients for the scale proof (G6).

    Creates 4 archetypes × 25 clients, each with positions copied verbatim from
    the corresponding Sample mandate portfolio and DNA authored from the archetype
    template. Requires /admin/seed/portfolio to have run first. Idempotent.
    """
    try:
        counts = await load_synthetic_clients(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        log.error("admin.seed_synthetic_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": counts}


@router.post("/seed/dna")
async def seed_dna(session: AsyncSession = Depends(get_session)) -> dict:
    """Extract DNA for all four personas from their CRM interaction notes.

    Requires /admin/seed/crm to have run first. Idempotent.
    """
    try:
        counts = await extract_dna(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        log.error("admin.seed_dna_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": counts}


@router.post("/seed/style-profile")
async def seed_style_profile(session: AsyncSession = Depends(get_session)) -> dict:
    """Extract communication style profiles from CRM notes (TASK-017).

    Requires /admin/seed/dna to have run first. Idempotent.
    """
    try:
        counts = await extract_style_profiles(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        log.error("admin.seed_style_profile_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": counts}


@router.post("/seed/fit")
async def seed_fit(session: AsyncSession = Depends(get_session)) -> dict:
    """Compute DNA-vs-tag fit scores for all clients (enriched_holdings.fit_score + conflicts).

    Requires /admin/seed/tags and /admin/seed/dna to have run first. Idempotent.
    """
    try:
        counts = await compute_fit(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        log.error("admin.seed_fit_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": counts}


@router.post("/seed/persona-portfolios")
async def seed_persona_portfolios(session: AsyncSession = Depends(get_session)) -> dict:
    """Attach real portfolios to the four CRM personas, then recompute derived data.

    Copies each persona's mandate-matching Sample portfolio onto them as owned
    positions (no fallback), then runs the non-LLM derived pipeline against the
    persona's OWN DNA: fit → swap → drift → alerts → rank. Requires /seed/portfolio,
    /seed/crm and /seed/dna to have run first. Idempotent.
    """
    try:
        link = await link_persona_portfolios(session)
        fit = await compute_fit(session)
        swap = await compute_swaps(session)
        drift = await compute_drift(session)
        alerts = await generate_alerts(session)
        rank = await rank_alerts(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        log.error("admin.seed_persona_portfolios_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "status": "ok",
        "loaded": {
            "link": link,
            "fit": fit,
            "swap": swap,
            "drift": drift,
            "alerts": alerts,
            "rank": rank,
        },
    }


@router.post("/seed/swap")
async def seed_swap(session: AsyncSession = Depends(get_session)) -> dict:
    """Compute DNA-conflict swap candidates for all clients (swap_proposals table).

    Requires /admin/seed/fit to have run first. Idempotent: deletes and reloads
    proposals per client on each call.
    """
    try:
        counts = await compute_swaps(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        log.error("admin.seed_swap_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": counts}


@router.post("/seed/embeddings")
async def seed_embeddings(session: AsyncSession = Depends(get_session)) -> dict:
    """Embed all CRM notes and ClientDNA rows into pgvector (TASK-015).

    Requires /admin/seed/crm to have run first (notes must exist).
    ClientDNA rows are optional — returns 0 gracefully if none exist yet.
    Requires `nomic-embed-text` to be pulled in Ollama:
      docker compose exec ollama ollama pull nomic-embed-text
    Idempotent: replaces existing embeddings for each owner on re-run.
    """
    try:
        interactions = await seed_interaction_embeddings(session)
        dna = await seed_dna_embeddings(session)
    except Exception as exc:
        log.error("admin.seed_embeddings_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": {"interactions": interactions, "client_dna": dna}}


@router.post("/seed/enrich")
async def seed_enrich(session: AsyncSession = Depends(get_session)) -> dict:
    """Resolve live EOD prices from SIX for all real-persona holdings (TASK-026).

    Writes enriched_holdings.live_price + live_price_at and computes positions.quantity.
    Bond SAC positions use par-pricing (current_chf / 100). Falls back gracefully
    when SIX is unavailable. Requires /admin/seed/tags to have run first. Idempotent.
    """
    try:
        counts = await enrich_holdings(session)
    except Exception as exc:
        log.error("admin.seed_enrich_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": counts}


@router.post("/seed/watchlist")
async def seed_watchlist(session: AsyncSession = Depends(get_session)) -> dict:
    """Build per-client watchlists from held entities + DNA themes (TASK-027).

    Requires /admin/seed/portfolio and /admin/seed/dna to have run first. Idempotent.
    """
    try:
        counts = await build_watchlists(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        log.error("admin.seed_watchlist_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": counts}


@router.get("/budget")
async def get_budget() -> dict:
    """Hosted-LLM token budget readout for the active provider's current UTC day.

    Returns spent / cap / remaining / exhausted. Local Ollama is unmetered
    (`metered: false`). Surfaces the budget guard so exhaustion is explicit, never
    silently degraded (no-fallbacks rule).
    """
    return {"status": "ok", "budget": await budget_status()}


@router.post("/scan/news")
async def scan_news(session: AsyncSession = Depends(get_session)) -> dict:
    """Fetch live news for all clients and match to their watchlists (TASK-028).

    Requires /admin/seed/watchlist to have run first.
    Idempotent: articles already in news_items (by URI) are skipped on re-run.
    """
    try:
        counts = await scan_news_all_clients(session)
    except Exception as exc:
        log.error("admin.scan_news_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": counts}


@router.post("/fanout/news")
async def fanout_news(session: AsyncSession = Depends(get_session)) -> dict:
    """Dequeue one article from news:candidates and fan it out to matching clients (TASK-030).

    Requires /admin/seed/watchlist to have run first. Idempotent: upserts by URI.
    Returns immediately with {"article": null, ...} when the queue is empty.
    """
    try:
        result = await run_fanout(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        log.error("admin.fanout_news_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "result": result}


@router.post("/scan/prices")
async def scan_prices(session: AsyncSession = Depends(get_session)) -> dict:
    """Scan held instruments via SIX → price_move / maturity_soon alerts (EPIC-08).

    The free (non-token-metered) proactive axis; runs continuously via the
    price-watch loop, exposed here for on-demand/demo use. Requires SIX_MCP_TOKEN
    and a seeded portfolio. Idempotent per client.
    """
    try:
        counts = await scan_price_signals(session)
    except Exception as exc:
        log.error("admin.scan_prices_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": counts}


@router.post("/seed/drift")
async def seed_drift(session: AsyncSession = Depends(get_session)) -> dict:
    """Compute drift breach and stale-SELL alerts for all clients (TASK-022).

    Requires /admin/seed/portfolio to have run first. Idempotent: deletes and
    reloads drift_breach + stale_sell alerts per client on each call.
    """
    try:
        counts = await compute_drift(session)
    except Exception as exc:
        log.error("admin.seed_drift_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": counts}


@router.post("/seed/rank")
async def seed_rank(session: AsyncSession = Depends(get_session)) -> dict:
    """Compute and persist rank_score for all open alerts (TASK-034 / AL6).

    Requires seed/alerts and seed/drift to have run first. Idempotent — safe to
    re-run after any alert regeneration pass.
    """
    try:
        counts = await rank_alerts(session)
    except Exception as exc:
        log.error("admin.seed_rank_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": counts}


@router.post("/seed/radar")
async def seed_radar(session: AsyncSession = Depends(get_session)) -> dict:
    """Rebuild the book-wide Change Radar (TASK-059 / EPIC-08).

    Inverts current Alert + NewsItem signals into event-centric change_events with
    impacted-client fan-out and aggregate impact scoring. Also folds in live email
    signals (TASK-060) so a single radar build sees every channel. Run AFTER
    seed/alerts, seed/drift, and scan/news so all signals exist. Idempotent — full
    rebuild. Email signals are empty when MS_GRAPH_* is unset (no crash).
    """
    try:
        email_signals = await ingest_email_signals(session)
        counts = await build_change_radar(session, extra_signals=email_signals)
    except Exception as exc:
        log.error("admin.seed_radar_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": {**counts, "email_signals": len(email_signals)}}


@router.post("/ingest/email")
async def ingest_email(session: AsyncSession = Depends(get_session)) -> dict:
    """Pull recent mail from Microsoft Graph and rebuild the radar with it (TASK-060).

    Classifies each thread with the local LLM, resolves its instrument/client/book
    entity, and folds the resulting signals into a full Change Radar rebuild. Returns
    a no-op {signals: 0} when MS_GRAPH_* is unset; raises 500 when Graph is configured
    but unreachable (no-fallbacks). Requires the radar's upstream signals to exist.
    """
    try:
        email_signals = await ingest_email_signals(session)
        counts = await build_change_radar(session, extra_signals=email_signals)
    except Exception as exc:
        log.error("admin.ingest_email_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "signals": len(email_signals), "loaded": counts}


@router.post("/seed/news")
async def seed_news(session: AsyncSession = Depends(get_session)) -> dict:
    """Seed the four demo persona trigger articles (TASK-031).

    Inserts scripted articles for Schneider, Huber, Räber, and Ammann so the
    demo works offline without live Event Registry coverage (§14.4, G6), then fans
    each out to every holder of the instruments it names so the radar shows them as
    multi-client events. Idempotent by event_cluster_id. Requires /seed/portfolio.
    Seeding order: seed/dna → seed/news.
    """
    try:
        counts = await seed_news_triggers(session)
        fanout = await fanout_seeded_news(session)
    except Exception as exc:
        log.error("admin.seed_news_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": {**counts, "fanout": fanout}}


@router.post("/seed/alerts")
async def seed_alerts(session: AsyncSession = Depends(get_session)) -> dict:
    """Generate alerts from all signal sources for all clients (TASK-032).

    Produces 8 non-drift alert classes: news_impact, good_news, panic,
    dna_conflict, values_drift, quiet_client, overdue_promise, behavioural_guardrail.
    drift_breach and stale_sell are owned by /admin/seed/drift — not touched here.

    Requires seed/portfolio + seed/crm + seed/dna + seed/tags + seed/fit to have run first.
    News-derived alerts degrade gracefully if scan/news has not been run yet.
    Idempotent: deletes and reloads the 8 managed alert classes per client.
    """
    try:
        counts = await generate_alerts(session)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        log.error("admin.seed_alerts_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": counts}


@router.post("/assemble/fact-sheet")
async def assemble_fact_sheet_ep(
    client_id: uuid.UUID,
    alert_id: uuid.UUID | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Deterministically assemble the MSG2 fact sheet for a client (TASK-037).

    Picks the most recent open dna_conflict alert unless alert_id is given.
    Creates a MessageDraft row with fact_sheet populated and status=draft.
    No LLM is called — all values come directly from engine + DNA + news tables.

    Requires: seed/portfolio → seed/crm → seed/dna → seed/tags → seed/fit →
              seed/swap → seed/alerts
              (scan/news optional — enriches evidence[] if available)
    """
    try:
        result = await assemble_fact_sheet(session, client_id, alert_id)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        log.error("admin.assemble_fact_sheet_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": result}


@router.post("/render/message")
async def render_message_ep(
    draft_id: uuid.UUID,
    preset: str | None = None,
    session: AsyncSession = Depends(get_session),
) -> dict:
    """Render a MessageDraft's fact sheet into styled prose via LLM (TASK-038).

    Requires assemble/fact-sheet to have run first (draft must have fact_sheet populated).
    Applies MSG4 guardrail: rejects if draft contains numbers not in the fact sheet.
    Optional preset overrides the client's style profile (data-driven/values-led/balanced).
    """
    try:
        result = await render_message_draft(session, draft_id, preset_override=preset)
    except RuntimeError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except Exception as exc:
        log.error("admin.render_message_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": result}



@router.post("/seed/personas")
async def seed_personas_ep(session: AsyncSession = Depends(get_session)) -> dict:
    """Run the full end-to-end pipeline for the four real personas (TASK-055).

    Executes all 14 steps in dependency order:
      portfolio → crm → tags → dna → style_profile → fit → swap → enrich →
      watchlist → news (D3 triggers) → alerts → drift → rank → message

    All steps are idempotent — safe to call on a cold DB or to re-run after any
    individual step is updated. SIX pricing falls back gracefully when offline.
    Message drafts (step 14) are best-effort: a persona with no dna_conflict
    alert is skipped rather than failing the entire pipeline.
    """
    try:
        result = await seed_personas(session, settings.wealth_data_dir)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=500, detail=f"Workbook not found: {exc}") from exc
    except Exception as exc:
        log.error("admin.seed_personas_failed", error=str(exc))
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {"status": "ok", "loaded": result}
