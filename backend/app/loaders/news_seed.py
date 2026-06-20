"""Seeded news trigger articles for the four demo personas (TASK-031, EPIC-07).

Four scripted articles are inserted once (idempotent by event_cluster_id) so
demo paths work offline without live Event Registry coverage (§14.4, G6).
All rows are labelled is_seeded=True and source ends in "[SEEDED]" to satisfy
the G6 provenance requirement.

Also exports is_duplicate_cluster() — a pure utility for TASK-030's fan-out
to suppress duplicate sources per breaking story before writing a NewsItem
(§14.2 F5, AL5).

Seeding order: seed/portfolio → seed/dna → seed/news
"""

from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logging import get_logger
from app.models.derived import NewsItem

log = get_logger(__name__)

# Four scripted articles, one per persona use-case (§D3):
#  Schneider → behavioural guardrail (neuro-research red line in CRM notes)
#  Huber     → non-financial moment (sustainability milestone → reach-out)
#  Räber     → swap trigger (CIO-SELL holding posts negative earnings)
#  Ammann    → good-news moment (luxury tilt confirmed by sector rally)
_TRIGGER_ARTICLES: list[dict] = [
    {
        "event_cluster_id": "seeded-cluster-schneider-pharma-2026",
        "headline": "AstraZeneca Shuts Down Neurological Disease Research Unit, Citing Cost Pressures",
        "source": "Reuters [SEEDED]",
        "url": "https://seeded.internal/schneider-pharma-trigger",
        "published_at": datetime(2026, 6, 18, 9, 0, tzinfo=timezone.utc),
        "sentiment": -0.72,
        "impact": "threat",
        "matched_holdings": [],
        "matched_themes": ["neuro-research", "pharma"],
    },
    {
        "event_cluster_id": "seeded-cluster-huber-esg-2026",
        "headline": "EU Sustainable Finance Package Passes — Green Bond Market to Double by 2028",
        "source": "Financial Times [SEEDED]",
        "url": "https://seeded.internal/huber-esg-trigger",
        "published_at": datetime(2026, 6, 17, 14, 30, tzinfo=timezone.utc),
        "sentiment": 0.81,
        "impact": "moment",
        "matched_holdings": [],
        "matched_themes": ["sustainability", "fossil-fuel"],
    },
    {
        "event_cluster_id": "seeded-cluster-raeber-intel-2026",
        "headline": "Intel Posts Fourth Consecutive Quarter of Revenue Decline Amid PC Market Slump",
        "source": "Bloomberg [SEEDED]",
        "url": "https://seeded.internal/raeber-intel-trigger",
        "published_at": datetime(2026, 6, 19, 7, 0, tzinfo=timezone.utc),
        "sentiment": -0.65,
        "impact": "threat",
        "matched_holdings": [{"issuer": "Intel", "isin": "US4581401001", "valor": "905718"}],
        "matched_themes": ["us-tech"],
    },
    {
        "event_cluster_id": "seeded-cluster-ammann-luxury-2026",
        "headline": "LVMH and Richemont Report Record Q2 Sales as Asian Luxury Demand Rebounds",
        "source": "WSJ [SEEDED]",
        "url": "https://seeded.internal/ammann-luxury-trigger",
        "published_at": datetime(2026, 6, 16, 11, 0, tzinfo=timezone.utc),
        "sentiment": 0.88,
        "impact": "opportunity",
        "matched_holdings": [],
        "matched_themes": ["luxury"],
    },
]


async def seed_news_triggers(session: AsyncSession) -> dict[str, int]:
    """Insert the four demo trigger articles if not already present.

    Idempotent by event_cluster_id: a second call skips all four and returns
    {"inserted": 0, "skipped": 4}. Commits once at the end.
    """
    inserted = 0
    skipped = 0

    for article in _TRIGGER_ARTICLES:
        cluster_id = article["event_cluster_id"]
        existing = await session.scalar(
            select(NewsItem).where(NewsItem.event_cluster_id == cluster_id).limit(1)
        )
        if existing is not None:
            log.info("news_seed.skipped", cluster_id=cluster_id)
            skipped += 1
            continue

        session.add(
            NewsItem(
                event_cluster_id=cluster_id,
                headline=article["headline"],
                source=article["source"],
                url=article["url"],
                published_at=article["published_at"],
                sentiment=article["sentiment"],
                impact=article["impact"],
                matched_holdings=article["matched_holdings"],
                matched_themes=article["matched_themes"],
                is_seeded=True,
            )
        )
        inserted += 1
        log.info("news_seed.inserted", cluster_id=cluster_id)

    await session.commit()
    log.info("news_seed.complete", inserted=inserted, skipped=skipped)
    return {"inserted": inserted, "skipped": skipped}


def is_duplicate_cluster(existing_cluster_ids: set[str], cluster_id: str | None) -> bool:
    """Return True if cluster_id is non-null and already in the known set.

    Used by the TASK-030 fan-out pipeline to suppress duplicate sources per
    breaking story before writing a NewsItem to the database (§14.2 F5, AL5).

    Pass None for ungrouped articles — they always pass through (returns False).
    """
    if not cluster_id:
        return False
    return cluster_id in existing_cluster_ids
