"""Tests for Codeforces 3000+ rating strategy selection."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import strategy_catalog as catalog  # noqa: E402


def test_strategy_catalog_uses_rating_not_algorithm_count():
    cards = catalog.recommend_strategies({"kind": "test-selection"})

    assert [card.key for card in cards] == ["weighted-coverage"]
    assert "branch-and-bound" in cards[0].complexity


def test_strategy_catalog_is_deterministic_and_constraint_aware():
    query = {"kind": "unknown", "constraints": ["context-retrieval"]}

    assert catalog.recommend_strategies(query) == catalog.recommend_strategies(query)
    assert "bm25-graph-expansion" in {card.key for card in catalog.recommend_strategies(query)}
