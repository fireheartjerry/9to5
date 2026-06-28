"""Tests for human_nature/emotions.py (Phase 3.5b).

Tests cover:
- couple() behavior is None when HN_EMOTIONS_BEHAVIOR=False (default)
- couple() behavior is correct string when behavior_enabled=True
- comms always contains "functional"
- bias_appraisal() shifts ambiguous valence negative when morale<0
- regulate() decays PAD magnitudes toward homeostatic zero
- Manipulation guard: couple() has no user-affect parameter (inspect.signature)
"""
from __future__ import annotations

import inspect

from human_nature.emotions import bias_appraisal, couple, regulate


# ---------------------------------------------------------------------------
# couple() — affect → behavior/comms coupling
# ---------------------------------------------------------------------------

def test_behavior_is_none_when_flag_off_by_default():
    """HN_EMOTIONS_BEHAVIOR defaults False; behavior must be None."""
    for label in ("frustration", "curiosity", "anxiety", "boredom", "satisfaction", "neutral"):
        result = couple(label, {})
        assert result["behavior"] is None, f"expected None for {label}, got {result['behavior']}"


def test_behavior_frustration_when_enabled():
    result = couple("frustration", {}, behavior_enabled=True)
    assert result["behavior"] == "escalate_effort"


def test_behavior_curiosity_when_enabled():
    result = couple("curiosity", {}, behavior_enabled=True)
    assert result["behavior"] == "explore"


def test_behavior_anxiety_when_enabled():
    result = couple("anxiety", {}, behavior_enabled=True)
    assert result["behavior"] == "raise_verification"


def test_behavior_boredom_when_enabled():
    result = couple("boredom", {}, behavior_enabled=True)
    assert result["behavior"] == "propose_refactor"


def test_behavior_satisfaction_is_comms_only_even_when_enabled():
    """Satisfaction → comms only; behavior stays None even with flag ON."""
    result = couple("satisfaction", {}, behavior_enabled=True)
    assert result["behavior"] is None


def test_comms_always_contains_functional():
    for label in ("frustration", "curiosity", "anxiety", "satisfaction", "neutral", "boredom"):
        result = couple(label, {})
        assert "functional" in result["comms"], (
            f"comms missing 'functional' for label={label!r}: {result['comms']!r}"
        )


def test_comms_does_not_contain_bare_i_feel():
    """comms must not start with a bare 'I feel' — that would be affect theater."""
    for label in ("frustration", "curiosity", "anxiety", "satisfaction"):
        result = couple(label, {})
        assert not result["comms"].strip().lower().startswith("i feel"), (
            f"comms is bare 'I feel' for {label}: {result['comms']!r}"
        )


def test_couple_returns_both_keys():
    result = couple("neutral", {})
    assert "behavior" in result
    assert "comms" in result


# ---------------------------------------------------------------------------
# Manipulation guard — inspect.signature (F8)
# ---------------------------------------------------------------------------

def test_couple_has_no_user_affect_parameter():
    """couple() must NOT accept the user's emotion state as input (F8 manipulation guard).

    This is asserted via inspect.signature so the guard cannot be bypassed by a
    caller — if any parameter named user_affect/user_emotion/user_mood appears, the
    test fails.
    """
    sig = inspect.signature(couple)
    _FORBIDDEN = {"user_affect", "user_emotion", "user_mood", "user_feeling"}
    for param_name in sig.parameters:
        assert param_name.lower() not in _FORBIDDEN, (
            f"couple() must not accept user affect as input (manipulation guard); "
            f"found forbidden parameter: {param_name!r}"
        )


# ---------------------------------------------------------------------------
# bias_appraisal() — mood-congruent appraisal bias
# ---------------------------------------------------------------------------

def test_bias_shifts_zero_valence_negative_when_morale_negative():
    """Low morale biases ambiguous (near-zero) valence negative."""
    pad = {"valence": 0.0, "arousal": 0.3, "control": 0.5, "vars": {}}
    biased = bias_appraisal(pad, morale=-0.8)
    assert biased["valence"] < 0.0, (
        f"expected negative valence, got {biased['valence']}"
    )


def test_bias_does_not_flip_strong_positive_valence():
    """Strong positive valence should not be flipped negative by morale bias."""
    pad = {"valence": 0.9, "arousal": 0.2, "control": 0.8, "vars": {}}
    biased = bias_appraisal(pad, morale=-1.0)
    # It may reduce the magnitude slightly, but should not go below 0
    assert biased["valence"] > 0.0, (
        f"strong positive valence should remain positive; got {biased['valence']}"
    )


def test_bias_does_not_change_valence_when_morale_nonnegative():
    """Positive or zero morale → no mood-congruent shift."""
    pad = {"valence": 0.0, "arousal": 0.3, "control": 0.5, "vars": {}}
    biased = bias_appraisal(pad, morale=0.0)
    assert biased["valence"] == pad["valence"]
    biased_pos = bias_appraisal(pad, morale=0.5)
    assert biased_pos["valence"] == pad["valence"]


def test_bias_returns_new_dict_not_mutated():
    pad = {"valence": 0.0, "arousal": 0.3, "control": 0.5, "vars": {}}
    biased = bias_appraisal(pad, morale=-0.5)
    assert biased is not pad  # new dict, not in-place mutation
    assert pad["valence"] == 0.0  # original unchanged


# ---------------------------------------------------------------------------
# regulate() — homeostatic decay toward zero
# ---------------------------------------------------------------------------

def test_regulate_reduces_arousal_magnitude():
    pad = {"valence": 0.8, "arousal": 0.9, "control": -0.6, "vars": {}}
    regulated = regulate(pad)
    assert abs(regulated["arousal"]) < abs(pad["arousal"])


def test_regulate_reduces_valence_magnitude():
    pad = {"valence": 0.8, "arousal": 0.9, "control": -0.6, "vars": {}}
    regulated = regulate(pad)
    assert abs(regulated["valence"]) < abs(pad["valence"])


def test_regulate_reduces_control_magnitude():
    pad = {"valence": 0.8, "arousal": 0.9, "control": -0.6, "vars": {}}
    regulated = regulate(pad)
    assert abs(regulated["control"]) < abs(pad["control"])


def test_regulate_returns_new_dict():
    pad = {"valence": 0.5, "arousal": 0.5, "control": 0.5, "vars": {}}
    regulated = regulate(pad)
    assert regulated is not pad


def test_regulate_custom_decay():
    pad = {"valence": 1.0, "arousal": 1.0, "control": 1.0, "vars": {}}
    regulated = regulate(pad, decay=0.5)
    # With decay=0.5, retention=0.5: new values should be 0.5
    assert abs(regulated["valence"] - 0.5) < 1e-9
    assert abs(regulated["arousal"] - 0.5) < 1e-9
