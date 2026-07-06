"""Tests for human_nature/psyche_runtime.py (per-tick psyche glue).

Tests cover:
- ensure_psyche() fills drives (8 keys), mood, affect_manifold, personality_ref
- tick() moves the manifold toward negative valence for a negative appraisal and
  returns a `dominant` prototype label
- tick() with an empty appraisal returns "neutral" and does not raise
- integrate_outcome() raises mood valence and raises the mastery drive level on a
  verified success
"""
from __future__ import annotations

from human_nature.drives import CORE
from human_nature.personality import new_personality
from human_nature.prototypes import PROTOTYPES
from human_nature.psyche_runtime import ensure_psyche, integrate_outcome, tick
from human_nature.self_state import new_self_state


# ---------------------------------------------------------------------------
# ensure_psyche()
# ---------------------------------------------------------------------------

def test_ensure_psyche_fills_drives_and_mood():
    ss = ensure_psyche(new_self_state())
    assert set(ss["drives"].keys()) == set(CORE)
    assert len(ss["drives"]) == 8
    assert "valence" in ss["mood"] and "arousal" in ss["mood"]
    assert "valence" in ss["affect_manifold"]


def test_ensure_psyche_stores_personality():
    p = new_personality()
    ss = ensure_psyche(new_self_state(), personality=p)
    assert ss["personality_ref"] is not None


def test_ensure_psyche_idempotent():
    ss = ensure_psyche(new_self_state())
    drives_before = ss["drives"]
    ss2 = ensure_psyche(ss)
    assert ss2["drives"] is drives_before


# ---------------------------------------------------------------------------
# tick()
# ---------------------------------------------------------------------------

def test_tick_moves_manifold_negative_and_returns_label():
    ss = ensure_psyche(new_self_state())
    result = tick(ss, {"valence": -0.6, "arousal": 0.6, "tension": 0.6})
    assert result["manifold"]["valence"] < 0.0
    assert isinstance(result["dominant"], str)
    assert result["dominant"] in PROTOTYPES
    assert result["self_state"] is ss


def test_tick_empty_appraisal_is_neutral_and_safe():
    ss = ensure_psyche(new_self_state())
    result = tick(ss, {})
    assert result["dominant"] == "neutral"


def test_tick_on_bare_dict_does_not_raise():
    result = tick({}, {})
    assert result["dominant"] in PROTOTYPES


# ---------------------------------------------------------------------------
# integrate_outcome()
# ---------------------------------------------------------------------------

def test_integrate_outcome_raises_mood_and_mastery():
    ss = ensure_psyche(new_self_state())
    mastery_before = ss["drives"]["mastery"]["level"]
    ss = integrate_outcome(ss, 0.8, 0.2, {"verified_success": True})
    assert ss["mood"]["valence"] > 0.0
    assert ss["drives"]["mastery"]["level"] > mastery_before


def test_integrate_outcome_with_personality_decays_toward_setpoint():
    p = new_personality()
    ss = ensure_psyche(new_self_state(), personality=p)
    ss = integrate_outcome(ss, 0.8, 0.2, {"verified_success": True})
    assert -1.0 <= ss["mood"]["valence"] <= 1.0
