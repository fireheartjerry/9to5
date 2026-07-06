"""Tests for human_nature/mood.py (slow persistent affective homeostat).

Tests cover:
- new_mood() defaults to valence/arousal 0.0
- blend_outcome() moves mood toward a run signal by `weight` (exponential moving average)
- decay() moves mood toward a personality setpoint by `rate`
- congruent_bias() pulls ambiguous (low-magnitude) valence toward mood valence,
  while protecting strong-magnitude valence from being flipped
- all outputs stay in [-1, 1]
- pure functions: inputs are never mutated
"""
from __future__ import annotations

from human_nature.mood import blend_outcome, congruent_bias, decay, new_mood


# ---------------------------------------------------------------------------
# new_mood()
# ---------------------------------------------------------------------------

def test_new_mood_defaults_to_zero():
    mood = new_mood()
    assert mood == {"valence": 0.0, "arousal": 0.0}


# ---------------------------------------------------------------------------
# blend_outcome() — exponential moving average toward a run signal
# ---------------------------------------------------------------------------

def test_blend_outcome_moves_toward_run_signal():
    mood = {"valence": 0.0, "arousal": 0.0}
    blended = blend_outcome(mood, run_valence=1.0, run_arousal=1.0, weight=0.3)
    assert abs(blended["valence"] - 0.3) < 1e-9
    assert abs(blended["arousal"] - 0.3) < 1e-9


def test_blend_outcome_default_weight():
    mood = {"valence": 0.0, "arousal": 0.0}
    blended = blend_outcome(mood, run_valence=1.0, run_arousal=1.0)
    assert abs(blended["valence"] - 0.3) < 1e-9


def test_blend_outcome_clamps_to_range():
    mood = {"valence": 1.0, "arousal": 1.0}
    blended = blend_outcome(mood, run_valence=1.0, run_arousal=1.0, weight=0.5)
    assert -1.0 <= blended["valence"] <= 1.0
    assert -1.0 <= blended["arousal"] <= 1.0


def test_blend_outcome_does_not_mutate_input():
    mood = {"valence": 0.0, "arousal": 0.0}
    blend_outcome(mood, run_valence=1.0, run_arousal=1.0, weight=0.3)
    assert mood == {"valence": 0.0, "arousal": 0.0}


def test_blend_outcome_returns_new_dict():
    mood = {"valence": 0.0, "arousal": 0.0}
    blended = blend_outcome(mood, run_valence=1.0, run_arousal=1.0)
    assert blended is not mood


# ---------------------------------------------------------------------------
# decay() — move mood toward a setpoint
# ---------------------------------------------------------------------------

def test_decay_moves_halfway_to_setpoint():
    mood = {"valence": 0.8, "arousal": 0.0}
    setpoint = {"valence": 0.0, "arousal": 0.0}
    decayed = decay(mood, setpoint, rate=0.5)
    assert abs(decayed["valence"] - 0.4) < 1e-9
    assert abs(decayed["arousal"] - 0.0) < 1e-9


def test_decay_zero_rate_is_no_change():
    mood = {"valence": 0.8, "arousal": -0.3}
    setpoint = {"valence": 0.0, "arousal": 0.0}
    decayed = decay(mood, setpoint, rate=0.0)
    assert abs(decayed["valence"] - 0.8) < 1e-9
    assert abs(decayed["arousal"] - (-0.3)) < 1e-9


def test_decay_full_rate_snaps_to_setpoint():
    mood = {"valence": 0.8, "arousal": -0.3}
    setpoint = {"valence": 0.2, "arousal": 0.1}
    decayed = decay(mood, setpoint, rate=1.0)
    assert abs(decayed["valence"] - 0.2) < 1e-9
    assert abs(decayed["arousal"] - 0.1) < 1e-9


def test_decay_clamps_to_range():
    mood = {"valence": 1.0, "arousal": 1.0}
    setpoint = {"valence": 1.0, "arousal": 1.0}
    decayed = decay(mood, setpoint, rate=0.5)
    assert -1.0 <= decayed["valence"] <= 1.0
    assert -1.0 <= decayed["arousal"] <= 1.0


def test_decay_does_not_mutate_inputs():
    mood = {"valence": 0.8, "arousal": 0.0}
    setpoint = {"valence": 0.0, "arousal": 0.0}
    decay(mood, setpoint, rate=0.5)
    assert mood == {"valence": 0.8, "arousal": 0.0}
    assert setpoint == {"valence": 0.0, "arousal": 0.0}


# ---------------------------------------------------------------------------
# congruent_bias() — mood-congruent bias on ambiguous valence
# ---------------------------------------------------------------------------

def test_congruent_bias_pulls_ambiguous_valence_negative():
    biased = congruent_bias(0.05, {"valence": -0.8, "arousal": 0.0})
    assert biased < 0.05


def test_congruent_bias_protects_strong_valence():
    biased = congruent_bias(0.9, {"valence": -0.8, "arousal": 0.0})
    assert abs(biased - 0.9) < 0.1
    assert biased > 0.0


def test_congruent_bias_no_shift_when_mood_neutral():
    biased = congruent_bias(0.05, {"valence": 0.0, "arousal": 0.0})
    assert abs(biased - 0.05) < 1e-9


def test_congruent_bias_no_shift_when_mood_positive():
    biased = congruent_bias(0.05, {"valence": 0.8, "arousal": 0.0})
    assert biased >= 0.05


def test_congruent_bias_clamps_to_range():
    biased = congruent_bias(-0.95, {"valence": -1.0, "arousal": 0.0}, strength=1.0)
    assert -1.0 <= biased <= 1.0


def test_congruent_bias_does_not_mutate_mood():
    mood = {"valence": -0.8, "arousal": 0.0}
    congruent_bias(0.05, mood)
    assert mood == {"valence": -0.8, "arousal": 0.0}
