import pytest
from learning import insight


def test_score_poignancy_failed_high_attempts_is_high():
    row = {"verify_passed": 0, "attempt_count": 3, "adversary_verdict": "challenged"}
    assert insight.score_poignancy(row) >= 0.8


def test_score_poignancy_clean_pass_is_low():
    row = {"verify_passed": 1, "attempt_count": 1, "adversary_verdict": "approved"}
    assert insight.score_poignancy(row) <= 0.3


def test_importance_trigger_only_fires_past_budget():
    assert insight.should_consolidate(0.4, budget=1.0) is False
    assert insight.should_consolidate(1.5, budget=1.0) is True
