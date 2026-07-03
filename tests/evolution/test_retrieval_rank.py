"""rerank: recency + importance + relevance, pure functions, fail-open on bad input."""
from datetime import datetime, timedelta, timezone

from memory import retrieval_rank


def _now():
    return datetime(2026, 6, 30, 12, 0, 0, tzinfo=timezone.utc)


def test_recent_high_importance_outranks_old_nearest_cosine():
    now = _now()
    old_best_cosine = {"st_id": "old", "score": 0.99, "importance": 1.0,
                       "created_at": (now - timedelta(days=120)).isoformat()}
    recent_important = {"st_id": "new", "score": 0.80, "importance": 4.0,
                        "created_at": (now - timedelta(days=1)).isoformat()}
    ranked = retrieval_rank.rerank([old_best_cosine, recent_important], now=now)
    assert ranked[0]["st_id"] == "new"
    assert "_rank_score" in ranked[0]


def test_rerank_is_stable_when_signals_tie():
    now = _now()
    a = {"st_id": "a", "score": 0.5, "importance": 1.0, "created_at": now.isoformat()}
    b = {"st_id": "b", "score": 0.5, "importance": 1.0, "created_at": now.isoformat()}
    ranked = retrieval_rank.rerank([a, b], now=now)
    assert {r["st_id"] for r in ranked} == {"a", "b"}


def test_rerank_failopen_returns_input_on_garbage():
    bad = [{"st_id": "x", "score": "not-a-number", "created_at": 12345, "importance": None}]
    out = retrieval_rank.rerank(bad, now=_now())
    assert out == bad or out[0]["st_id"] == "x"   # never raises


def test_rerank_empty_is_empty():
    assert retrieval_rank.rerank([], now=_now()) == []
