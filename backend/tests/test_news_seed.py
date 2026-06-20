"""Unit tests for backend/app/loaders/news_seed.py (TASK-031).

Pure-function tests need no DB or network. Pattern mirrors tests/test_news.py.
"""

from app.loaders.news_seed import _TRIGGER_ARTICLES, is_duplicate_cluster


# ---------------------------------------------------------------------------
# is_duplicate_cluster — pure function
# ---------------------------------------------------------------------------

def test_is_duplicate_cluster_hit():
    assert is_duplicate_cluster({"a", "b"}, "a") is True


def test_is_duplicate_cluster_miss():
    assert is_duplicate_cluster({"a", "b"}, "c") is False


def test_is_duplicate_cluster_none_passthrough():
    assert is_duplicate_cluster({"a"}, None) is False


def test_is_duplicate_cluster_empty_string_passthrough():
    assert is_duplicate_cluster({"a"}, "") is False


def test_is_duplicate_cluster_empty_set():
    assert is_duplicate_cluster(set(), "x") is False


def test_is_duplicate_cluster_large_set():
    ids = {f"cluster-{i}" for i in range(1000)}
    assert is_duplicate_cluster(ids, "cluster-500") is True
    assert is_duplicate_cluster(ids, "cluster-9999") is False


# ---------------------------------------------------------------------------
# _TRIGGER_ARTICLES — data integrity
# ---------------------------------------------------------------------------

def test_trigger_articles_count():
    assert len(_TRIGGER_ARTICLES) == 4


def test_trigger_articles_cluster_ids_unique():
    ids = [a["event_cluster_id"] for a in _TRIGGER_ARTICLES]
    assert len(set(ids)) == 4


def test_trigger_articles_all_have_seeded_source_label():
    for a in _TRIGGER_ARTICLES:
        assert "[SEEDED]" in a["source"], f"Missing [SEEDED] label in source: {a['source']}"


def test_trigger_articles_impacts_cover_all_d3_use_cases():
    impacts = {a["impact"] for a in _TRIGGER_ARTICLES}
    assert "threat" in impacts
    assert "moment" in impacts
    assert "opportunity" in impacts


def test_trigger_articles_all_have_themes():
    for a in _TRIGGER_ARTICLES:
        assert isinstance(a["matched_themes"], list)
        assert len(a["matched_themes"]) >= 1


def test_trigger_articles_published_at_timezone_aware():
    for a in _TRIGGER_ARTICLES:
        assert a["published_at"].tzinfo is not None, (
            f"published_at must be timezone-aware: {a['event_cluster_id']}"
        )


def test_trigger_articles_sentiment_in_range():
    for a in _TRIGGER_ARTICLES:
        assert -1.0 <= a["sentiment"] <= 1.0
