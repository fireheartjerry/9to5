from __future__ import annotations

import pytest

from human_nature.conflict import dissonance, route


def test_agreeing_signals_high_calibration_low_dissonance():
    d = dissonance(0.8, 0.75, 0.7, self_model_calibration=0.9)
    assert d < 0.3


def test_disagreeing_signals_low_calibration_high_dissonance():
    d = dissonance(1.0, -1.0, 1.0, self_model_calibration=0.1)
    assert d > 0.6


def test_dissonance_bounded_agree():
    assert 0.0 <= dissonance(0.8, 0.75, 0.7, self_model_calibration=0.9) <= 1.0


def test_dissonance_bounded_disagree():
    assert 0.0 <= dissonance(1.0, -1.0, 1.0, self_model_calibration=0.1) <= 1.0


@pytest.mark.parametrize(
    "opinion,intuition,instinct,calibration",
    [
        (0.5, 0.5, 0.5, 0.5),
        (-1.0, -1.0, -1.0, 1.0),
        (1.0, 0.0, -1.0, 0.0),
        (0.0, 0.0, 0.0, 0.5),
    ],
)
def test_dissonance_always_in_unit_range(opinion, intuition, instinct, calibration):
    d = dissonance(opinion, intuition, instinct, self_model_calibration=calibration)
    assert 0.0 <= d <= 1.0


def test_route_high_dissonance_with_debate_budget():
    assert route(0.8, {"debate": 1}) == "debate"


def test_route_high_dissonance_without_debate_budget():
    assert route(0.8, {"debate": 0}) == "deepen_verify"


def test_route_moderate_dissonance():
    assert route(0.5, {}) == "deepen_verify"


def test_route_low_dissonance():
    assert route(0.1, {}) == "none"


def test_route_very_high_dissonance_allows_replan():
    assert route(0.9, {"debate": 0, "allow_replan": True}) == "replan"


def test_route_very_high_dissonance_no_replan_budget_falls_back_to_deepen_verify():
    assert route(0.9, {"debate": 0}) == "deepen_verify"


def test_route_very_high_dissonance_with_debate_still_debates():
    assert route(0.9, {"debate": 1, "allow_replan": True}) == "debate"
