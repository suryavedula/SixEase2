"""Inverted-index fan-out + LLM triage (TASK-030, EPIC-07).

Consumes articles from the Redis queue written by the firehose poller (TASK-029)
and routes each article to the matching clients in O(article) time via an inverted
index (§14.2 F3). A cheap pre-filter limits LLM calls to the shortlist (§14.2 F4).
Matched articles are upserted as NewsItem rows; per-client candidates are emitted
to the alert-engine input queue for TASK-032.

Seeding order: seed/portfolio → seed/dna → seed/watchlist → (poller feeds the queue)

Lifecycle (from main.py):
    task = start_fanout()    # startup
    await stop_fanout(task)  # shutdown
"""

import asyncio
import contextlib
import json
import uuid

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import SessionFactory
from app.llm import json_chat
from app.loaders.embeddings import relevance_distances
from app.loaders.rerank import passes_cross_encoder
from app.logging import get_logger
from app.models.derived import ClientWatchlist, NewsItem
from app.news import NewsArticle
from app.redis_client import dequeue, enqueue, redis_client

# Reuse matching primitives from TASK-028 (pure functions, no I/O).
from app.loaders.news_match import (
    _ImpactResult,
    _build_impact_messages,
    _llm_financial_filter,
    _match_article,
    _parse_published_at,
)

log = get_logger(__name__)
settings = get_settings()

_CANDIDATE_QUEUE = "news:candidates"       # TASK-029 writes here; we read
_ALERT_QUEUE = "news:alert_candidates"     # TASK-032 reads here; we write

_SHORTLIST_SENTIMENT: float = 0.2
_SHORTLIST_MIN_HITS: int = 2

# Impact-classification dedup: the costliest per-(article, client) hosted-LLM call.
# A lost poller cursor re-flows the same articles; without this guard each replay
# re-spends. We remember scored pairs for a week so replays skip straight past.
_CLASSIFIED_TTL_SECONDS: int = 7 * 24 * 3600


def _classified_key(article_uri: str, client_id_str: str) -> str:
    return f"news:classified:{article_uri}:{client_id_str}"


# ---------------------------------------------------------------------------
# Inverted index
# ---------------------------------------------------------------------------


async def build_inverted_index(
    session: AsyncSession,
) -> dict[str, list[tuple[str, ClientWatchlist]]]:
    """Build keyword → [(client_id_str, watchlist)] mapping from all watchlist rows.

    Raises RuntimeError when no watchlist rows exist (seed guard).
    O(clients × keywords_per_client) build; O(index_keywords) fan-out per article.
    """
    rows = (await session.execute(select(ClientWatchlist))).scalars().all()
    if not rows:
        raise RuntimeError(
            "No client_watchlists rows found — run /admin/seed/watchlist first"
        )

    index: dict[str, list[tuple[str, ClientWatchlist]]] = {}
    for row in rows:
        client_id_str = str(row.client_id)
        for kw in row.keywords or []:
            key = kw.lower()
            if key not in index:
                index[key] = []
            index[key].append((client_id_str, row))

    log.info(
        "fanout.index_built",
        clients=len(rows),
        unique_keywords=len(index),
    )
    return index


# ---------------------------------------------------------------------------
# Core fan-out
# ---------------------------------------------------------------------------


async def run_fanout(session: AsyncSession) -> dict:
    """Dequeue one article from news:candidates, fan-out to matching clients.

    Returns {"article": uri | None, "matched": N, "shortlisted": M, "emitted": K}.
    Idempotent: re-processing the same article URI upserts the existing NewsItem row.
    """
    payload = await dequeue(_CANDIDATE_QUEUE, timeout=1)
    if payload is None:
        return {"article": None, "matched": 0, "shortlisted": 0, "emitted": 0}

    article = NewsArticle.model_validate(payload)

    text = (article.title + " " + article.body).lower()

    # Coarse keyword fan-out FIRST (free) — candidate clients via the inverted index.
    # Only articles that hit some watchlist proceed to a hosted-LLM call, instead of
    # classifying every firehose article (the old per-article filter; §14.2 F4).
    index = await build_inverted_index(session)
    client_hits: dict[str, ClientWatchlist] = {}
    for keyword, entries in index.items():
        if keyword in text:
            for client_id_str, watchlist in entries:
                client_hits.setdefault(client_id_str, watchlist)

    if not client_hits:
        log.info("fanout.no_matches", article_uri=article.uri)
        return {"article": article.uri, "matched": 0, "shortlisted": 0, "emitted": 0}

    # Drop non-financial noise — one LLM call, ONLY for watchlist-hitting articles.
    # No fail-open: on LLM error, re-enqueue for retry rather than silently treating
    # the article as relevant (no-fallbacks rule).
    try:
        relevant = await _llm_financial_filter([article])
    except Exception as exc:
        log.error("fanout.filter_error_requeue", article_uri=article.uri, error=str(exc))
        await enqueue(_CANDIDATE_QUEUE, payload)
        await asyncio.sleep(2)  # avoid a tight retry loop while the LLM is unreachable
        return {"article": article.uri, "matched": 0, "shortlisted": 0, "emitted": 0, "error": "filter"}
    if not relevant:
        log.info("fanout.filtered_out", article_uri=article.uri, title=article.title)
        return {"article": article.uri, "matched": 0, "shortlisted": 0, "emitted": 0}

    # Per-client relevance: cosine distance of the article to each DNA profile vector
    # (local Ollama embedding, zero Phoeniqs cost). Gates care-axis-only matches —
    # the local answer to "does this news affect the client profile?". Degrades to {}
    # (no gating) when embeddings are unavailable; never blocks fan-out.
    relevance = await relevance_distances(session, f"{article.title} {article.body}")

    # Per-client: precise two-axis match + relevance gate + shortlist + LLM triage.
    shortlisted = 0
    emitted = 0
    relevance_dropped = 0
    cross_encoder_dropped = 0
    verification_dropped = 0
    all_client_ids: list[str] = []
    all_own_hits: list[dict] = []
    all_care_hits: list[dict] = []
    best_impact: str | None = None
    best_confidence: float = 0.0

    for client_id_str, watchlist in client_hits.items():
        own_hits, care_hits = _match_article(article, watchlist)
        total_hits = len(own_hits) + len(care_hits)

        if total_hits == 0:
            continue  # keyword matched text but two-axis scan found nothing — skip

        # Relevance gate: care-axis-only matches must sit near the client's DNA
        # profile vector. A direct holding (own-axis) match is trusted and bypasses it.
        if not own_hits:
            dist = relevance.get(client_id_str)
            if dist is not None and dist > settings.news_relevance_max_distance:
                relevance_dropped += 1
                log.info(
                    "fanout.relevance_dropped",
                    article_uri=article.uri, client_id=client_id_str, distance=round(dist, 3),
                )
                continue

        impact: str | None = None
        reason: str | None = None
        confidence: float | None = None

        on_shortlist = (
            abs(article.sentiment or 0) >= _SHORTLIST_SENTIMENT
            or total_hits >= _SHORTLIST_MIN_HITS
        )
        if on_shortlist:
            # Dedup: if this (article, client) pair was already scored, reuse the
            # cached verdict instead of re-spending a hosted-LLM call on a replay.
            cache_key = _classified_key(article.uri, client_id_str)
            cached = await redis_client.get(cache_key)
            if cached is not None:
                verdict = json.loads(cached)
                if not verdict.get("about_holding", True):
                    verification_dropped += 1
                    log.info(
                        "fanout.verification_dropped_cached",
                        article_uri=article.uri, client_id=client_id_str,
                    )
                    continue
                impact = verdict.get("impact")
                reason = verdict.get("reason")
                confidence = verdict.get("confidence")
                if (confidence or 0) > best_confidence:
                    best_confidence = confidence or 0
                    best_impact = impact
            else:
                # Cross-encoder precision gate (local, no Phoeniqs) — drop vocabulary-
                # overlap false positives BEFORE spending a hosted-LLM call. No-op when
                # disabled. Own-axis (direct holding) matches are trusted and bypass it.
                if care_hits and not own_hits:
                    ce_ok, ce_score = await passes_cross_encoder(
                        f"{article.title} {article.body}", own_hits, care_hits
                    )
                    if not ce_ok:
                        cross_encoder_dropped += 1
                        log.info(
                            "fanout.cross_encoder_dropped",
                            article_uri=article.uri, client_id=client_id_str,
                            score=None if ce_score is None else round(ce_score, 3),
                        )
                        continue

                shortlisted += 1
                try:
                    result = await json_chat(
                        _build_impact_messages(article, own_hits, care_hits),
                        _ImpactResult,
                    )
                    # Cache the verdict (incl. negatives) so replays never re-spend.
                    await redis_client.set(
                        cache_key,
                        json.dumps(
                            {
                                "about_holding": result.about_holding,
                                "impact": result.impact,
                                "reason": result.reason,
                                "confidence": result.confidence,
                            }
                        ),
                        ex=_CLASSIFIED_TTL_SECONDS,
                    )
                    # Entity-grounding gate: drop wrong-entity / incidental-word matches.
                    if not result.about_holding:
                        verification_dropped += 1
                        log.info(
                            "fanout.verification_dropped",
                            article_uri=article.uri, client_id=client_id_str,
                        )
                        continue
                    impact = result.impact
                    reason = result.reason
                    confidence = result.confidence
                    if (confidence or 0) > best_confidence:
                        best_confidence = confidence
                        best_impact = impact
                except Exception as exc:
                    log.warning("fanout.classify_failed", uri=article.uri, error=str(exc))

        all_client_ids.append(client_id_str)

        # Accumulate union of axis hits across clients for the shared NewsItem row.
        for hit in own_hits:
            if hit not in all_own_hits:
                all_own_hits.append(hit)
        for hit in care_hits:
            if hit not in all_care_hits:
                all_care_hits.append(hit)

        candidate = {
            "article_uri": article.uri,
            "client_id": client_id_str,
            "matched_holdings": own_hits,
            "matched_themes": care_hits,
            "impact": impact,
            "impact_reason": reason,
            "confidence": confidence,
            "sentiment": article.sentiment,
            "news_item_id": None,  # filled in after upsert below
        }
        await enqueue(_ALERT_QUEUE, candidate)
        emitted += 1

    if not all_client_ids:
        return {
            "article": article.uri,
            "matched": 0,
            "shortlisted": shortlisted,
            "relevance_dropped": relevance_dropped,
            "cross_encoder_dropped": cross_encoder_dropped,
            "verification_dropped": verification_dropped,
            "emitted": 0,
        }

    # Upsert ONE NewsItem row per article, aggregating all matched client_ids.
    stmt = (
        pg_insert(NewsItem)
        .values(
            headline=article.title,
            source=article.source,
            url=article.url,
            published_at=_parse_published_at(article.published_at),
            sentiment=article.sentiment,
            matched_holdings=all_own_hits or None,
            matched_themes=all_care_hits or None,
            impact=best_impact,
            event_cluster_id=article.uri,
            client_ids=all_client_ids,
            is_seeded=False,
        )
        .on_conflict_do_update(
            index_elements=["event_cluster_id"],
            set_={
                "client_ids": all_client_ids,
                "matched_holdings": all_own_hits or None,
                "matched_themes": all_care_hits or None,
                "impact": best_impact,
            },
        )
    )
    await session.execute(stmt)
    await session.commit()

    log.info(
        "fanout.article_processed",
        article_uri=article.uri,
        matched=len(all_client_ids),
        shortlisted=shortlisted,
        relevance_dropped=relevance_dropped,
        cross_encoder_dropped=cross_encoder_dropped,
        verification_dropped=verification_dropped,
        emitted=emitted,
    )
    return {
        "article": article.uri,
        "matched": len(all_client_ids),
        "shortlisted": shortlisted,
        "relevance_dropped": relevance_dropped,
        "cross_encoder_dropped": cross_encoder_dropped,
        "verification_dropped": verification_dropped,
        "emitted": emitted,
    }


# ---------------------------------------------------------------------------
# Background consumer lifecycle (mirrors poller.py pattern)
# ---------------------------------------------------------------------------


async def _fanout_loop() -> None:
    """Continuous consumer: dequeue → fan-out → repeat. No sleep needed — dequeue
    blocks for 1 second when the queue is empty, providing natural back-pressure."""
    log.info("fanout.started")
    while True:
        try:
            async with SessionFactory() as session:
                await run_fanout(session)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("fanout.cycle_error", error=str(exc))


def start_fanout() -> "asyncio.Task[None]":
    """Spawn the fanout consumer as a named asyncio background task."""
    return asyncio.create_task(_fanout_loop(), name="news-fanout")


async def stop_fanout(task: "asyncio.Task[None]") -> None:
    """Cancel the fanout consumer and wait for it to finish."""
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task
    log.info("fanout.stopped")
