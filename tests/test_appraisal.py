"""Tests for human_nature/appraisal.py (Phase 3.5a).

Tests cover:
- appraise() → correct PAD coords per event mix
- emotion_label() → region mapping
- PAD values stay within spec ranges
"""
from __future__ import annotations

from human_nature.appraisal import appraise, emotion_label


# ---------------------------------------------------------------------------
# appraise() — PAD coordinate derivation
# ---------------------------------------------------------------------------

def test_all_success_low_novelty_produces_positive_valence():
    events = [{"outcome": "success", "novelty": 0.0, "agency": 1.0},
              {"outcome": "success", "novelty": 0.0, "agency": 1.0}]
    pad = appraise(events)
    assert pad["valence"] > 0.3
    assert pad["arousal"] < 0.5


def test_failure_streak_produces_negative_valence_high_arousal_low_control():
    events = [{"outcome": "failure", "novelty": 0.0, "agency": 0.2}] * 3
    pad = appraise(events)
    assert pad["valence"] < -0.3
    assert pad["arousal"] > 0.5
    assert pad["control"] < 0.5


def test_high_novelty_produces_high_arousal():
    events = [{"outcome": "success", "novelty": 0.9, "agency": 0.5}]
    pad = appraise(events)
    assert pad["arousal"] > 0.5


def test_empty_events_returns_neutral_pad():
    pad = appraise([])
    assert pad["valence"] == 0.0
    assert pad["arousal"] == 0.0
    # control may vary but must be in range
    assert -1.0 <= pad["control"] <= 1.0


def test_pad_values_stay_in_range():
    # extremes: all failures, zero agency, full novelty
    e1 = [{"outcome": "failure", "novelty": 1.0, "agency": 0.0}] * 5
    # extremes: all successes, full agency, zero novelty
    e2 = [{"outcome": "success", "novelty": 0.0, "agency": 1.0}] * 5
    # mixed
    e3 = [{"outcome": "success", "novelty": 0.5}, {"outcome": "failure"}]
    for events in (e1, e2, e3):
        pad = appraise(events)
        assert -1.0 <= pad["valence"] <= 1.0, f"valence out of range: {pad['valence']}"
        assert 0.0 <= pad["arousal"] <= 1.0, f"arousal out of range: {pad['arousal']}"
        assert -1.0 <= pad["control"] <= 1.0, f"control out of range: {pad['control']}"


def test_appraise_vars_present():
    pad = appraise([{"outcome": "success"}])
    v = pad.get("vars", {})
    for key in ("goal_congruence", "self_agency", "novelty", "certainty", "coping"):
        assert key in v, f"missing vars key: {key}"


# ---------------------------------------------------------------------------
# emotion_label() — region mapping
# ---------------------------------------------------------------------------

def test_all_success_low_novelty_is_satisfaction():
    events = [{"outcome": "success", "novelty": 0.0, "agency": 1.0}] * 3
    pad = appraise(events)
    assert emotion_label(pad) == "satisfaction"


def test_failure_streak_is_frustration():
    events = [{"outcome": "failure", "novelty": 0.0, "agency": 0.2}] * 3
    pad = appraise(events)
    assert emotion_label(pad) == "frustration"


def test_high_novelty_success_is_curiosity():
    events = [{"outcome": "success", "novelty": 0.8, "agency": 0.5}]
    pad = appraise(events)
    assert emotion_label(pad) == "curiosity"


def test_empty_events_is_neutral():
    pad = appraise([])
    assert emotion_label(pad) == "neutral"


def test_explicit_neutral_pad():
    pad = {"valence": 0.1, "arousal": 0.2, "control": 0.1, "vars": {"novelty": 0.1}}
    assert emotion_label(pad) == "neutral"


def test_anxiety_label():
    # negative valence, high arousal, HIGH control (not frustration)
    pad = {"valence": -0.6, "arousal": 0.8, "control": 0.7, "vars": {"novelty": 0.1}}
    assert emotion_label(pad) == "anxiety"
