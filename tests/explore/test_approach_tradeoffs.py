"""Tests for explore.approach_tradeoffs -- deterministic trade-off scoring."""
from __future__ import annotations

from developer_tools.introspection import extractProject

from developer_tools.exploration.approach_gen import generateApproaches
from developer_tools.exploration.approach_tradeoffs import (
    W_EFFORT,
    W_FIT,
    W_RISK,
    W_TESTABILITY,
    scoreApproaches,
)


def test_weights_sum_to_one():
    assert abs(W_RISK + W_EFFORT + W_TESTABILITY + W_FIT - 1.0) < 1e-9


def test_scores_sorted_and_bounded(fixture_project):
    m = extractProject(fixture_project, use_cache=False)
    cands = generateApproaches("add input validation to pkg.core", m, n=5)
    scores = scoreApproaches(cands, m)
    assert len(scores) == 5
    totals = [s.total for s in scores]
    assert totals == sorted(totals, reverse=True)
    for s in scores:
        for field in (s.risk, s.effort, s.testability, s.fit, s.total):
            assert 0.0 <= field <= 1.0
        expected = round(
            W_RISK * s.risk
            + W_EFFORT * s.effort
            + W_TESTABILITY * s.testability
            + W_FIT * s.fit,
            4,
        )
        assert s.total == expected
        assert s.total == round(s.total, 4)


def test_scores_deterministic(fixture_project):
    m = extractProject(fixture_project, use_cache=False)
    cands = generateApproaches("goal", m, n=3)
    assert scoreApproaches(cands, m) == scoreApproaches(cands, m)


def test_testability_rewards_test_first_with_test_cmd(fixture_project):
    m = extractProject(fixture_project, use_cache=False)
    assert any(c.kind == "test" for c in m.commands)
    cands = generateApproaches("goal", m, n=5)
    by_arch = {s.approach_id: s for s in scoreApproaches(cands, m)}
    id_of = {c.archetype: c.approach_id for c in cands}
    assert by_arch[id_of["test-first"]].testability == 1.0
    assert by_arch[id_of["minimal-patch"]].testability == 0.7
