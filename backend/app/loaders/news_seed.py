"""Seeded news trigger articles for the four demo personas (TASK-031, EPIC-07).

Fetches real articles from Event Registry for the four persona trigger scenarios
instead of using hardcoded fake URLs. Takes the most-recent result per targeted
search and inserts it with is_seeded=True so fanout_seeded_news resolves it to
the matching portfolio holders.

Seeding order: seed/portfolio → seed/dna → seed/news
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models.derived import NewsItem
from app.news import search_articles

log = get_logger(__name__)

# One targeted search per persona scenario.
# keywords are chosen to surface the same class of story the scenario represents
# while being specific enough to avoid general noise.
_SEED_SEARCHES: list[dict] = [
    {
        "scenario": "schneider-pharma",
        "keywords": ["AstraZeneca", "neurological"],
        "description": "AstraZeneca neuro research — Schneider behavioural guardrail (DNA: neuro-research)",
    },
    {
        "scenario": "huber-esg",
        "keywords": ["green bond", "sustainable finance"],
        "description": "EU green finance regulation — Huber moment trigger (DNA: sustainability)",
    },
    {
        "scenario": "raeber-intel",
        "keywords": ["Intel", "earnings"],
        "description": "Intel financial results — Räber swap trigger (holds Intel)",
    },
    {
        "scenario": "ammann-luxury",
        "keywords": ["LVMH", "Richemont"],
        "description": "Luxury sector performance — Ammann good-news moment (DNA: luxury)",
    },
]


def _parse_published_at(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except ValueError:
        return None


async def seed_news_triggers(session: AsyncSession) -> dict[str, int]:
    """Fetch real Event Registry articles for the four demo scenarios.

    Takes the most-recent article per search query and inserts it with is_seeded=True
    so fanout_seeded_news can resolve it to portfolio holders. Idempotent by URI:
    articles already present as event_cluster_id are skipped. Re-running fetches
    fresh articles when old ones are no longer present.

    Raises RuntimeError if Event Registry is unreachable (no silent fallback).
    """
    inserted = 0
    skipped = 0
    not_found = 0

    for search in _SEED_SEARCHES:
        articles = await search_articles(keywords=search["keywords"], count=5)

        if not articles:
            log.warning(
                "news_seed.not_found",
                scenario=search["scenario"],
                keywords=search["keywords"],
            )
            not_found += 1
            continue

        article = articles[0]  # most-recent first (articlesSortBy: date)

        existing = await session.scalar(
            select(NewsItem)
            .where(NewsItem.event_cluster_id == article.uri)
            .limit(1)
        )
        if existing is not None:
            log.info("news_seed.skipped", scenario=search["scenario"], uri=article.uri)
            skipped += 1
            continue

        session.add(
            NewsItem(
                event_cluster_id=article.uri,
                headline=article.title,
                source=article.source,
                url=article.url,
                published_at=_parse_published_at(article.published_at),
                sentiment=article.sentiment,
                impact=None,  # classified downstream by fanout_seeded_news + LLM
                matched_holdings=[],
                matched_themes=[],
                is_seeded=True,
            )
        )
        inserted += 1
        log.info(
            "news_seed.inserted",
            scenario=search["scenario"],
            url=article.url,
            title=article.title,
        )

    await session.commit()
    log.info(
        "news_seed.complete",
        inserted=inserted,
        skipped=skipped,
        not_found=not_found,
    )
    return {"inserted": inserted, "skipped": skipped, "not_found": not_found}


def is_duplicate_cluster(existing_cluster_ids: set[str], cluster_id: str | None) -> bool:
    """Return True if cluster_id is non-null and already in the known set.

    Used by the TASK-030 fan-out pipeline to suppress duplicate sources per
    breaking story before writing a NewsItem to the database (§14.2 F5, AL5).
    Pass None for ungrouped articles — they always pass through (returns False).
    """
    if not cluster_id:
        return False
    return cluster_id in existing_cluster_ids
