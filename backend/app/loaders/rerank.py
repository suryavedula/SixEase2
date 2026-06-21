"""Cross-encoder rerank precision gate (EPIC-06 C2).

The bi-encoder DNA cosine gate (`embeddings.relevance_distances`) is recall-
oriented: cheap, but it keeps articles that merely share vocabulary with the
client's profile without really being about the matched holding. A *cross-encoder*
scores the (matched-entity context, article) pair JOINTLY with full cross-
attention, so it demotes exactly those vocabulary-overlap false positives — the
documented precision workhorse for entity/relevance matching.

It runs on the shortlist BEFORE the hosted-LLM impact call, so it both sharpens
precision and cuts Phoeniqs spend (a dropped pair never reaches the LLM). Fully
local via fastembed (onnxruntime) — no torch, no cloud, zero hosted-LLM budget.

Disabled by default (`news_cross_encoder_enabled`). When enabled it loads the
model eagerly on first use and RAISES on failure rather than silently passing
matches through (no-fallbacks rule). The heavy dependency `fastembed` is imported
lazily so this module — and the whole app — imports fine when the gate is off.
"""

import asyncio

from app.config import get_settings
from app.logging import get_logger

log = get_logger(__name__)
settings = get_settings()

# Lazily-constructed fastembed TextCrossEncoder singleton (model load is expensive
# and downloads weights on first use); only touched when the gate is enabled.
_encoder = None


def _get_encoder():
    """Return the cross-encoder singleton, importing fastembed lazily.

    Raises ImportError if the optional dependency is missing — surfaced to the
    caller rather than degrading to a no-op (no-fallbacks).
    """
    global _encoder
    if _encoder is None:
        try:  # import path differs across fastembed versions
            from fastembed import TextCrossEncoder
        except ImportError:
            from fastembed.rerank.cross_encoder import TextCrossEncoder
        _encoder = TextCrossEncoder(model_name=settings.news_cross_encoder_model)
        log.info("rerank.model_loaded", model=settings.news_cross_encoder_model)
    return _encoder


def _score_sync(query: str, document: str) -> float:
    """Synchronous single-pair score (CPU-bound ONNX inference)."""
    encoder = _get_encoder()
    return float(list(encoder.rerank(query, [document]))[0])


def build_query(matched_holdings: list[dict], matched_themes: list[dict]) -> str:
    """Compose the cross-encoder query from the matched entity/theme context.

    The query describes what we believe the article should be about; the
    cross-encoder then judges whether the article text actually supports it.
    """
    parts = [h["issuer"] for h in (matched_holdings or []) if h.get("issuer")]
    parts += [t["tag"] for t in (matched_themes or []) if t.get("tag")]
    return f"news about {', '.join(parts)}" if parts else "relevant financial news"


async def passes_cross_encoder(
    article_text: str,
    matched_holdings: list[dict],
    matched_themes: list[dict],
) -> tuple[bool, float | None]:
    """Cross-encoder precision gate for one (entity context, article) pair.

    Returns (passed, score). When the gate is disabled this is a no-op that
    returns (True, None) — an explicit configuration choice, not a fallback.
    When enabled, the sync ONNX inference is offloaded to a thread so it never
    blocks the event loop, and a low score (< `news_cross_encoder_min_score`)
    drops the match before any hosted-LLM call.
    """
    if not settings.news_cross_encoder_enabled:
        return True, None

    query = build_query(matched_holdings, matched_themes)
    score = await asyncio.to_thread(_score_sync, query, article_text)
    return score >= settings.news_cross_encoder_min_score, score
