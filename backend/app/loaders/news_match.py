"""News matching and impact classification pipeline (TASK-028, EPIC-06).

Matches NewsArticle objects against each client's watchlist on two axes:
  - own-axis:  article text contains a held entity (issuer / ticker / ISIN)
  - care-axis: article text contains a DNA theme keyword

For shortlisted articles an LLM classifies impact as threat / opportunity / moment.
Matched articles are persisted as NewsItem rows with full provenance (§13.2 N5).

Seeding order: seed/portfolio → seed/dna → seed/watchlist → scan/news
"""

import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.llm import json_chat
from app.logging import get_logger
from app.models.derived import ClientWatchlist, NewsItem
from app.models.source import Client
from app.news import NewsArticle, search_articles

log = get_logger(__name__)

_SHORTLIST_SENTIMENT: float = 0.2   # |sentiment| threshold for LLM classification
_SHORTLIST_MIN_HITS: int = 2        # minimum axis-hits threshold (alternative)
_FETCH_COUNT: int = 50              # articles per search_articles() call


# ---------------------------------------------------------------------------
# LLM output schema (private)
# ---------------------------------------------------------------------------


class _ImpactResult(BaseModel):
    impact: Literal["threat", "opportunity", "moment"]
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)


_IMPACT_SYSTEM = """\
You are a wealth management analyst. Given a news article and the specific client \
holding or theme that matched it, classify the article's impact on the client.

Output ONLY a valid JSON object — no markdown fences, no prose, no explanation.

Required schema:
{
  "impact": "threat",
  "reason": "brief explanation",
  "confidence": 0.8
}

Definitions:
- threat: negative news for a held position or value → candidate swap / alert (UC-3/UC-4)
- opportunity: positive news, cause milestone, or potential buy candidate (UC-17)
- moment: personal or cause-related news — best answered by outreach, not a trade (UC-6)\
"""


def _build_impact_messages(
    article: NewsArticle,
    matched_holdings: list[dict],
    matched_themes: list[dict],
) -> list[dict]:
    holding_str = (
        ", ".join(h["issuer"] for h in matched_holdings if h.get("issuer"))
        if matched_holdings
        else "none"
    )
    theme_str = (
        ", ".join(t["tag"] for t in matched_themes if t.get("tag"))
        if matched_themes
        else "none"
    )
    user = (
        f"Headline: {article.title}\n\n"
        f"Body (excerpt): {article.body[:500]}\n\n"
        f"Matched holdings: {holding_str}\n"
        f"Matched themes: {theme_str}\n\n"
        "Classify the impact."
    )
    return [
        {"role": "system", "content": _IMPACT_SYSTEM},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
# Matching helpers (pure functions — testable without I/O)
# ---------------------------------------------------------------------------


def _match_article(
    article: NewsArticle,
    watchlist: ClientWatchlist,
) -> tuple[list[dict], list[dict]]:
    """Return (matched_holdings, matched_themes); empty lists = no match on that axis."""
    text = (article.title + " " + article.body).lower()

    matched_holdings: list[dict] = []
    seen_isins: set[str] = set()
    for entity in watchlist.entities or []:
        issuer = entity.get("issuer") or ""
        ticker = entity.get("ticker") or ""
        isin = entity.get("isin") or ""

        # Collapse multiple positions in the same company by ISIN dedup
        if isin and isin in seen_isins:
            continue

        if (
            (issuer and issuer.lower() in text)
            or (ticker and ticker.lower() in text)
            or (isin and isin.lower() in text)
        ):
            matched_holdings.append(
                {
                    "issuer": issuer,
                    "valor": entity.get("valor") or "",
                    "isin": isin,
                    "ticker": ticker,
                    "axis": "own",
                }
            )
            if isin:
                seen_isins.add(isin)

    matched_themes: list[dict] = []
    seen_tags: set[str] = set()
    for tag in watchlist.themes or []:
        if tag and tag not in seen_tags and tag.lower() in text:
            matched_themes.append({"tag": tag, "axis": "care"})
            seen_tags.add(tag)

    return matched_holdings, matched_themes


def _parse_published_at(raw: str) -> datetime | None:
    """Parse ISO-8601 datetime string to UTC-aware datetime."""
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


async def match_articles(
    session: AsyncSession,
    client_id: uuid.UUID,
    watchlist: ClientWatchlist,
    articles: list[NewsArticle],
) -> dict[str, int]:
    """Match pre-fetched articles against a client's watchlist; persist new NewsItem rows.

    Returns {"matched": N, "classified": M, "inserted": K}.
    Idempotent: articles whose URI is already in event_cluster_id are skipped.
    """
    # Two-axis match + filter
    matched: list[tuple[NewsArticle, list[dict], list[dict]]] = []
    for article in articles:
        mh, mt = _match_article(article, watchlist)
        if mh or mt:
            matched.append((article, mh, mt))

    if not matched:
        log.info("news_match.no_matches", client_id=str(client_id))
        return {"matched": 0, "classified": 0, "inserted": 0}

    # Dedup: skip URIs already in the DB
    uris = [a.uri for a, _, _ in matched]
    existing_uris: set[str] = set(
        (
            await session.scalars(
                select(NewsItem.event_cluster_id).where(NewsItem.event_cluster_id.in_(uris))
            )
        ).all()
    )
    fresh = [(a, mh, mt) for a, mh, mt in matched if a.uri not in existing_uris]

    # LLM impact classification (shortlist only — cost control §14.2 F4)
    client_id_str = str(client_id)
    classified = 0
    rows: list[NewsItem] = []

    for article, mh, mt in fresh:
        total_hits = len(mh) + len(mt)
        impact: str | None = None
        if abs(article.sentiment or 0) >= _SHORTLIST_SENTIMENT or total_hits >= _SHORTLIST_MIN_HITS:
            try:
                result = await json_chat(_build_impact_messages(article, mh, mt), _ImpactResult)
                impact = result.impact
                classified += 1
            except Exception as exc:
                log.warning("news_match.classify_failed", uri=article.uri, error=str(exc))

        rows.append(
            NewsItem(
                headline=article.title,
                source=article.source,
                url=article.url,
                published_at=_parse_published_at(article.published_at),
                sentiment=article.sentiment,
                matched_holdings=mh,
                matched_themes=mt,
                impact=impact,
                event_cluster_id=article.uri,
                client_ids=[client_id_str],
                is_seeded=False,
            )
        )

    for row in rows:
        session.add(row)
    await session.commit()

    log.info(
        "news_match.client_scanned",
        client_id=client_id_str,
        matched=len(matched),
        classified=classified,
        inserted=len(rows),
    )
    return {"matched": len(matched), "classified": classified, "inserted": len(rows)}


async def scan_news_for_client(
    session: AsyncSession,
    client_id: uuid.UUID,
) -> dict[str, int]:
    """Fetch live news for one client and match to their watchlist.

    Raises RuntimeError if the watchlist has not been built (seed/watchlist guard).
    """
    watchlist = await session.scalar(
        select(ClientWatchlist).where(ClientWatchlist.client_id == client_id)
    )
    if watchlist is None:
        raise RuntimeError(
            f"No watchlist found for client {client_id} — run /admin/seed/watchlist first"
        )

    keywords = watchlist.keywords or []
    if not keywords:
        log.warning("news_match.empty_watchlist", client_id=str(client_id))
        return {"matched": 0, "classified": 0, "inserted": 0}

    articles = await search_articles(keywords=keywords, count=_FETCH_COUNT)
    log.info("news_match.fetched", client_id=str(client_id), articles=len(articles))
    return await match_articles(session, client_id, watchlist, articles)


async def scan_news_all_clients(session: AsyncSession) -> dict[str, dict]:
    """Scan news for all clients; returns {client_name: counts_dict}.

    Skips clients whose watchlist has not been built (warns instead of aborting).
    """
    clients = (await session.scalars(select(Client))).all()
    results: dict[str, dict] = {}

    for client in clients:
        try:
            counts = await scan_news_for_client(session, client.id)
            results[client.name] = counts
        except RuntimeError as exc:
            log.warning("news_match.client_skipped", client=client.name, reason=str(exc))
            results[client.name] = {"error": str(exc)}

    log.info("news_match.scan_complete", clients=len(results))
    return results
