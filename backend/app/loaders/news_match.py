"""News matching and impact classification pipeline (TASK-028, EPIC-06).

Matches NewsArticle objects against each client's watchlist on two axes:
  - own-axis:  article text contains a held entity (issuer / ticker / ISIN)
  - care-axis: article text contains a DNA theme keyword

For shortlisted articles an LLM classifies impact as threat / opportunity / moment.
Matched articles are persisted as NewsItem rows with full provenance (§13.2 N5).

Seeding order: seed/portfolio → seed/dna → seed/watchlist → scan/news
"""

import re
import unicodedata
import uuid
from datetime import datetime, timedelta, timezone
from typing import Literal

from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.llm import json_chat
from app.loaders.embeddings import relevance_distances
from app.loaders.rerank import passes_cross_encoder
from app.logging import get_logger
from app.models.derived import ClientWatchlist, NewsItem
from app.models.source import Client, Position
from app.news import NewsArticle, search_articles

log = get_logger(__name__)
settings = get_settings()

# ---------------------------------------------------------------------------
# LLM financial relevance pre-filter
# ---------------------------------------------------------------------------

_RELEVANCE_SYSTEM = """\
You are a financial news filter for a wealth advisory platform. \
Given a numbered list of article headlines and short excerpts, identify which are \
relevant to financial markets, investment, or business.

KEEP articles about: company earnings/results, stock or market movements, M&A deals, \
restructuring, regulatory changes affecting companies or markets, economic data \
(rates, inflation, GDP), ESG/sustainability tied to specific companies or regulations, \
sector and industry trends that affect investment theses.

DISCARD articles about: sports, entertainment, celebrity, general politics unrelated \
to business, crime, accidents, natural disasters (unless clearly market-moving), \
opinion pieces with no market data, social issues with no financial angle.

Output ONLY valid JSON with no markdown fences or prose:
{"relevant_indices": [0, 2, 5]}\
"""


class _RelevanceFilter(BaseModel):
    relevant_indices: list[int]


async def _llm_financial_filter(articles: list[NewsArticle]) -> list[NewsArticle]:
    """Drop non-financial noise via a single batched LLM call.

    Passes all article titles + snippets to the LLM in one request; the model
    returns the indices of articles worth keeping.

    Does NOT fail open: if the LLM call errors we raise rather than silently
    passing every article through as "relevant" (no-fallbacks rule — surface the
    error and let the caller decide whether to retry). Callers must handle the
    exception explicitly.
    """
    if not articles:
        return []

    numbered = "\n".join(
        f"{i}. [{a.source}] {a.title} — {(a.body or '')[:150].strip()}"
        for i, a in enumerate(articles)
    )
    messages = [
        {"role": "system", "content": _RELEVANCE_SYSTEM},
        {"role": "user", "content": f"Articles:\n{numbered}"},
    ]
    result = await json_chat(messages, _RelevanceFilter, max_tokens=512)
    kept = [articles[i] for i in result.relevant_indices if 0 <= i < len(articles)]
    log.info(
        "news_match.relevance_filter",
        total=len(articles),
        kept=len(kept),
        dropped=len(articles) - len(kept),
    )
    return kept


# Generic issuer-name tokens that would over-match a headline ("Swiss Bank",
# "... Group", "ZKB Bond"). Significant tokens are everything else of length ≥4.
_ISSUER_STOPWORDS: frozenset[str] = frozenset(
    {
        # entity-type / legal-form words
        "corp", "corporation", "incorporated", "company", "holding", "holdings",
        "group", "groupe", "limited", "listed", "investments", "investment",
        "financiere", "compagnie", "moet", "hennessy", "bank", "banque",
        # financial-instrument words (avoid matching "bonds", "shares" in headlines)
        "bond", "bonds", "note", "notes", "account", "shares", "share", "stock",
        "stocks", "equity", "equities", "index", "trust", "capital", "fund",
        "etf", "yield", "rate", "rates",
        # geography / generic descriptors
        "swiss", "suisse", "gold", "cash", "republic", "confederation",
        "treasury", "government", "global", "mandate", "property", "real",
        "estate", "domestic", "foreign", "markets", "market",
        # nationality / region tokens — sovereign bonds & regional index funds have
        # names built entirely from these ("United Mexican States", "Emerging
        # Markets"); single tokens like "mexican"/"america" match news incidentally,
        # so they cannot identify the instrument. Address those by ISIN/ticker, not name.
        "united", "states", "state", "mexican", "mexico", "american", "america",
        "european", "europe", "eurozone", "asian", "asia", "china", "chinese",
        "japan", "japanese", "india", "indian", "korea", "korean", "kingdom",
        "britain", "british", "germany", "german", "france", "french", "italy",
        "italian", "spain", "spanish", "latin", "nordic", "pacific", "world",
        "international", "emerging", "developed", "sovereign",
        # fund / ETF structure + provider tokens — descriptive, not identifying.
        "ishares", "xtrackers", "vanguard", "spdr", "lyxor", "invesco", "amundi",
        "wisdomtree", "private", "dividend", "select", "sector", "aggregate",
        "sustainable", "factor", "quality", "momentum", "growth", "value", "core",
        "broad", "duration", "ultrashort", "listed",
    }
)

_SHORTLIST_SENTIMENT: float = 0.2   # |sentiment| threshold for LLM classification
_SHORTLIST_MIN_HITS: int = 2        # minimum axis-hits threshold (alternative)
_FETCH_COUNT: int = 50              # articles per search_articles() call
_LOOKBACK_DAYS: int = 30            # only the last month's news about a held stock

# Issuer name-tokens that are also common English words ("Apple", "Total",
# "Visa", "Shell"). A whole-word hit on one of these is NOT enough on its own —
# it must be corroborated by a second signal (an unambiguous holding match, a
# care-axis theme hit, or material sentiment) before it counts. This kills the
# bulk of the false positives. Curated, lowercased, de-accented; extend as the
# portfolio universe grows. Distinctive names (Richemont, Nestlé, AstraZeneca,
# LVMH, ASML, …) are deliberately absent — they match on a single signal.
_AMBIGUOUS_TOKENS: frozenset[str] = frozenset(
    {
        "apple", "visa", "total", "shell", "orange", "gap", "sun", "key",
        "ally", "ball", "general", "united", "american", "national",
        "standard", "first", "next", "square", "block", "match", "open",
        # common-word tickers — would over-match even in a headline
        # (ServiceNow=NOW, Costco=COST, On Holding=ON, Allstate=ALL).
        "now", "cost", "on", "all", "are", "it", "for", "one", "out",
    }
)


# ---------------------------------------------------------------------------
# LLM output schema (private)
# ---------------------------------------------------------------------------


class _ImpactResult(BaseModel):
    # Entity-grounding verification (precision gate): is the article ACTUALLY about
    # the matched holding/theme, or did it match on an incidental word / a different
    # company of the same name? Defaults True for backward compatibility; the prompt
    # instructs the model to set it False on a spurious match, and callers drop those.
    about_holding: bool = True
    impact: Literal["threat", "opportunity", "moment"]
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)


_IMPACT_SYSTEM = """\
You are a wealth management analyst. Given a news article and the specific client \
holding or theme that matched it, FIRST verify the match, then classify the impact.

Verification (precision gate): set "about_holding" to false if the article is NOT \
genuinely about the named company/theme — e.g. it only contains the word incidentally \
("apple" the fruit, "visa" the travel document), or it is about a DIFFERENT entity that \
merely shares the name. When in doubt that it is the right entity, set it false. \
Only set "about_holding" true when you are confident the article concerns the matched \
holding/theme. If false, still pick the least-wrong impact label but set confidence low.

Output ONLY a valid JSON object — no markdown fences, no prose, no explanation.

Required schema:
{
  "about_holding": true,
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


def _whole_word(token: str, text: str) -> bool:
    """True if `token` (already lowercased/de-accented) appears as a whole word."""
    return bool(token) and re.search(rf"\b{re.escape(token)}\b", text) is not None


def _entity_signals(entity: dict, title: str, body: str) -> tuple[bool, bool]:
    """Score one holding against de-accented (title, body).

    Returns (matched, strong):
      - matched: any whole-word hit (issuer token / ticker / ISIN) in title or body
      - strong:  hit via an UNAMBIGUOUS signal — ISIN, a real ticker symbol, or a
                 distinctive issuer token THAT APPEARS IN THE HEADLINE. The headline
                 is where an article's real subject lives, so a distinctive name found
                 only deep in the body (an incidental name-drop) stays weak and needs
                 corroboration — as do ambiguous common-word tokens ("apple", "total").
    Whole-word matching (not substring) stops "intel"→intelligence, "visa"→visacard.
    """
    full = f"{title} {body}"
    issuer = entity.get("issuer") or ""
    ticker = (entity.get("ticker") or "").split(".")[0].lower()  # drop ".SW"/".PA" suffix
    isin = (entity.get("isin") or "").lower()

    # ISIN — globally unique, unambiguous wherever it appears.
    if isin and _whole_word(isin, full):
        return True, True
    # Ticker base symbol — only trusted in the HEADLINE, never the free-text body.
    # A bare lowercased ticker is a common English word far too often (ServiceNow=NOW,
    # Costco=COST, On=ON): matched against the body it strong-matched the words "now"
    # and "cost" in nearly every article. The headline is where a ticker actually
    # denotes the stock; body-only ticker hits are dropped (the issuer-name path below
    # still catches a genuine in-body name-drop as a weak, corroboration-gated match).
    if len(ticker) >= 3 and ticker not in _AMBIGUOUS_TOKENS and _whole_word(ticker, title):
        return True, True
    # Issuer name tokens (distinctive, de-accented, len ≥ 4, non-generic).
    matched = strong = False
    for tok in significant_name_tokens(issuer):
        if _whole_word(tok, full):
            matched = True
            # Strong only if distinctive AND in the headline — not an incidental body mention.
            if tok not in _AMBIGUOUS_TOKENS and _whole_word(tok, title):
                strong = True
    return matched, strong


def _match_article(
    article: NewsArticle,
    watchlist: ClientWatchlist,
) -> tuple[list[dict], list[dict]]:
    """Return (matched_holdings, matched_themes); empty lists = no match on that axis.

    Precision rules (vs. the old naive substring scan):
      1. Whole-word matching only — no partial-word false positives.
      2. Two-signal gate — a holding that matched ONLY on a common-word token
         (e.g. "Apple") is dropped unless the article carries a second signal:
         an unambiguous holding match, a care-axis theme hit, or material sentiment.
    """
    title = _deaccent((article.title or "").lower())
    body = _deaccent((article.body or "").lower())
    text = f"{title} {body}"  # combined, for theme (care-axis) matching

    strong_holdings: list[dict] = []
    weak_holdings: list[dict] = []
    seen_isins: set[str] = set()
    for entity in watchlist.entities or []:
        isin = entity.get("isin") or ""
        if isin and isin in seen_isins:  # collapse same-company positions by ISIN
            continue

        matched, strong = _entity_signals(entity, title, body)
        if not matched:
            continue

        record = {
            "issuer": entity.get("issuer") or "",
            "valor": entity.get("valor") or "",
            "isin": isin,
            "ticker": entity.get("ticker") or "",
            "axis": "own",
        }
        (strong_holdings if strong else weak_holdings).append(record)
        if isin:
            seen_isins.add(isin)

    matched_themes: list[dict] = []
    seen_tags: set[str] = set()
    for tag in watchlist.themes or []:
        if tag and tag not in seen_tags and _whole_word(_deaccent(tag.lower()), text):
            matched_themes.append({"tag": tag, "axis": "care"})
            seen_tags.add(tag)

    # Two-signal gate: ambiguous-only (weak) holdings count only when the article
    # is corroborated by an unambiguous holding, a theme hit, or material sentiment.
    corroborated = (
        bool(strong_holdings)
        or bool(matched_themes)
        or abs(article.sentiment or 0) >= _SHORTLIST_SENTIMENT
    )
    matched_holdings = strong_holdings + (weak_holdings if corroborated else [])

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
    dropped_relevance = 0
    dropped_cross_encoder = 0
    dropped_verification = 0
    rows: list[NewsItem] = []

    for article, mh, mt in fresh:
        # Semantic relevance gate: a care-axis-only match (no direct holding) must be
        # near the client's DNA profile vector. Local Ollama embedding — no Phoeniqs
        # cost. Own-axis holding matches are trusted and bypass the gate.
        if not mh:
            distances = await relevance_distances(session, f"{article.title} {article.body}")
            dist = distances.get(client_id_str)
            if dist is not None and dist > settings.news_relevance_max_distance:
                dropped_relevance += 1
                log.info(
                    "news_match.relevance_dropped",
                    uri=article.uri, client_id=client_id_str, distance=round(dist, 3),
                )
                continue

        total_hits = len(mh) + len(mt)
        impact: str | None = None
        if abs(article.sentiment or 0) >= _SHORTLIST_SENTIMENT or total_hits >= _SHORTLIST_MIN_HITS:
            # Cross-encoder precision gate (local, no Phoeniqs) before the LLM call.
            # No-op when disabled; trusts own-axis holding matches.
            if mt and not mh:
                ce_ok, ce_score = await passes_cross_encoder(f"{article.title} {article.body}", mh, mt)
                if not ce_ok:
                    dropped_cross_encoder += 1
                    log.info(
                        "news_match.cross_encoder_dropped",
                        uri=article.uri, client_id=client_id_str,
                        score=None if ce_score is None else round(ce_score, 3),
                    )
                    continue
            try:
                result = await json_chat(_build_impact_messages(article, mh, mt), _ImpactResult)
                # Entity-grounding gate: drop spurious (wrong-entity / incidental-word) matches.
                if not result.about_holding:
                    dropped_verification += 1
                    log.info(
                        "news_match.verification_dropped",
                        uri=article.uri, client_id=client_id_str,
                    )
                    continue
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
        dropped_relevance=dropped_relevance,
        dropped_cross_encoder=dropped_cross_encoder,
        dropped_verification=dropped_verification,
        inserted=len(rows),
    )
    return {
        "matched": len(matched),
        "classified": classified,
        "dropped_relevance": dropped_relevance,
        "dropped_cross_encoder": dropped_cross_encoder,
        "dropped_verification": dropped_verification,
        "inserted": len(rows),
    }


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

    date_start = (datetime.now(timezone.utc) - timedelta(days=_LOOKBACK_DAYS)).strftime("%Y-%m-%d")
    # Relevance-sorted (not date): within the 30-day window we want the articles
    # actually ABOUT a held stock (issuer in the headline → strong match), not merely
    # the newest article that name-drops a watchlist token deep in its body.
    articles = await search_articles(
        keywords=keywords, count=_FETCH_COUNT, date_start=date_start, sort_by="rel"
    )
    log.info(
        "news_match.fetched",
        client_id=str(client_id),
        articles=len(articles),
        since=date_start,
    )
    articles = await _llm_financial_filter(articles)
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


# ---------------------------------------------------------------------------
# Seeded-news fan-out (offline demo) — TASK-061
# ---------------------------------------------------------------------------


def _deaccent(text: str) -> str:
    """Lowercase + strip diacritics so "Financière"→"financiere", "Nestlé"→"nestle"."""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def significant_name_tokens(issuer: str | None) -> list[str]:
    """Distinctive lowercased, de-accented name tokens (len ≥ 4, non-generic).

    Used both to match a headline to an issuer and to drop purely generic holdings
    ("Swiss Bank", "US Treasury") from the global news-firehose filter.
    """
    raw = re.sub(r"[^a-z0-9]+", " ", _deaccent(issuer or "")).split()
    return [t for t in raw if len(t) >= 4 and t not in _ISSUER_STOPWORDS]


def issuer_in_headline(issuer: str | None, headline_lower: str) -> bool:
    """True if any distinctive token of the issuer appears as a whole word in the headline.

    Pure + tolerant of the short-name/legal-name gap: positions store "Intel Corp." /
    "Compagnie Financière Richemont SA" while headlines say "Intel" / "Richemont".
    """
    text = _deaccent(headline_lower)
    return any(
        re.search(rf"\b{re.escape(tok)}\b", text)
        for tok in significant_name_tokens(issuer)
    )


async def fanout_seeded_news(session: AsyncSession) -> dict[str, int]:
    """Fan the seeded demo articles out to every holder of the instruments they name.

    The offline trigger articles (is_seeded=True) carry a headline but no body and no
    client_ids, so the radar never sees them. Here we resolve each headline to the
    instruments it mentions (issuer-token match against held Positions) and set
    client_ids = **all holders** of those instruments + matched_holdings, so a story on
    a widely-held name (e.g. LVMH, held by 6) becomes one multi-client radar event.
    Deterministic, no LLM. Idempotent — recomputes on every run. Articles that resolve
    to no held instrument are left untouched and logged (no silent drop).

    Run AFTER seed/watchlist + seed/news and BEFORE seed/alerts so news_impact alerts
    fire. Returns {"seeded_articles": N, "fanned_out": M, "unmatched": K}.
    """
    items = (
        await session.scalars(select(NewsItem).where(NewsItem.is_seeded.is_(True)))
    ).all()
    positions = (await session.scalars(select(Position))).all()

    # Instrument universe keyed by ISIN: issuer/valor + the set of clients holding it.
    universe: dict[str, dict] = {}
    for p in positions:
        if not p.isin:
            continue
        u = universe.setdefault(
            p.isin,
            {"issuer": p.issuer, "valor": p.valor, "isin": p.isin, "holders": set()},
        )
        u["holders"].add(str(p.client_id))

    fanned_out = 0
    unmatched = 0
    for item in items:
        headline = (item.headline or "").lower()
        client_ids: set[str] = set()
        matched_holdings: list[dict] = []
        seen_issuers: set[str] = set()
        for u in universe.values():
            if u["issuer"] in seen_issuers or not issuer_in_headline(u["issuer"], headline):
                continue
            seen_issuers.add(u["issuer"])
            client_ids |= u["holders"]
            matched_holdings.append(
                {
                    "issuer": u["issuer"],
                    "valor": u["valor"] or "",
                    "isin": u["isin"],
                    "ticker": "",
                    "axis": "own",
                }
            )

        if client_ids:
            item.client_ids = sorted(client_ids)
            item.matched_holdings = matched_holdings
            fanned_out += 1
            log.info(
                "news_match.seeded_fanned",
                headline=item.headline,
                clients=len(client_ids),
                instruments=len(matched_holdings),
            )
        else:
            # Idempotent: clear any stale fan-out from a prior run so an article that
            # no longer resolves to a held instrument stops showing as a radar event.
            item.client_ids = []
            item.matched_holdings = []
            unmatched += 1
            log.info("news_match.seeded_unmatched", headline=item.headline)

    await session.commit()
    log.info(
        "news_match.seeded_fanout_complete",
        seeded_articles=len(items),
        fanned_out=fanned_out,
        unmatched=unmatched,
    )
    return {"seeded_articles": len(items), "fanned_out": fanned_out, "unmatched": unmatched}
