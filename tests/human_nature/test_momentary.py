"""Tests for human_nature/momentary.py (Phase 3.1).

All LLM calls use injected fake ``chat`` callables — never hits the network.
"""
from __future__ import annotations

import itertools

import config
from human_nature.conviction import recalibrate
from human_nature.momentary import (
    cross_cast_agreement,
    self_consistency,
    verbalized_p_true,
)


def _fake_chat(reply: str):
    """Return a fake chat callable that always returns the given text."""
    def _chat(system, user):  # noqa: ARG001
        return {"message": {"content": reply}}
    return _chat


# ---------------------------------------------------------------------------
# verbalized_p_true — parsing
# ---------------------------------------------------------------------------

def test_parse_true():
    result = verbalized_p_true("sky is blue", chat=_fake_chat("TRUE"))
    assert result > 0.5
    assert result < 1.0  # recalibration pulls back from 1.0


def test_parse_false():
    result = verbalized_p_true("sky is green", chat=_fake_chat("FALSE"))
    assert result < 0.5
    assert result > 0.0  # recalibration pulls back from 0.0


def test_parse_numeric_decimal():
    result = verbalized_p_true("x", chat=_fake_chat("0.8"))
    expected = recalibrate(0.8, config.HN_RECAL_TEMPERATURE)
    assert abs(result - expected) < 1e-9


def test_parse_percent():
    result = verbalized_p_true("x", chat=_fake_chat("80%"))
    expected = recalibrate(0.80, config.HN_RECAL_TEMPERATURE)
    assert abs(result - expected) < 1e-9


def test_recalibration_applied_for_extreme_p():
    """TRUE raw=1.0 should differ from 1.0 after temperature scaling."""
    result = verbalized_p_true("x", chat=_fake_chat("TRUE"))
    assert result != 1.0  # temperature T=2.5 pulls toward 0.5


def test_parse_numeric_in_prose():
    """Parser extracts 0.7 from a sentence."""
    result = verbalized_p_true("x", chat=_fake_chat("I believe this is about 0.7 likely."))
    expected = recalibrate(0.7, config.HN_RECAL_TEMPERATURE)
    assert abs(result - expected) < 1e-9


def test_fallback_to_half_on_unparseable():
    """Unparseable reply falls back to 0.5 before recalibration."""
    result = verbalized_p_true("x", chat=_fake_chat("I dunno"))
    expected = recalibrate(0.5, config.HN_RECAL_TEMPERATURE)
    assert abs(result - expected) < 1e-9


# ---------------------------------------------------------------------------
# self_consistency
# ---------------------------------------------------------------------------

def test_self_consistency_unanimous():
    sampler = lambda: "yes"  # noqa: E731
    assert self_consistency(sampler, n=5) == 1.0


def test_self_consistency_split_2_3():
    answers = iter(["a", "a", "a", "b", "b"])
    sampler = lambda: next(answers)  # noqa: E731
    result = self_consistency(sampler, n=5)
    assert abs(result - 3 / 5) < 1e-9


def test_self_consistency_cycling():
    # a,a,b,a,a,b → 4 a, 2 b → 4/6
    cycle = itertools.cycle(["a", "a", "b"])
    sampler = lambda: next(cycle)  # noqa: E731
    result = self_consistency(sampler, n=6)
    assert abs(result - 4 / 6) < 1e-9


def test_self_consistency_single_sample():
    sampler = lambda: "x"  # noqa: E731
    assert self_consistency(sampler, n=1) == 1.0


# ---------------------------------------------------------------------------
# cross_cast_agreement
# ---------------------------------------------------------------------------

def test_cross_cast_empty():
    assert cross_cast_agreement([]) == 0.0


def test_cross_cast_aab():
    assert abs(cross_cast_agreement(["a", "a", "b"]) - 2 / 3) < 1e-9


def test_cross_cast_unanimous():
    assert cross_cast_agreement(["x", "x", "x"]) == 1.0


def test_cross_cast_single():
    assert cross_cast_agreement(["z"]) == 1.0


def test_cross_cast_two_equal_groups():
    # ["a","b","a","b"] → "a" appears 2 times = 2/4 = 0.5
    assert abs(cross_cast_agreement(["a", "b", "a", "b"]) - 0.5) < 1e-9
