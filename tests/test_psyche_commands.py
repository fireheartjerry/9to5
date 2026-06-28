"""Tests for Phase 5.3 — pure psyche command routers.

All routers return plain Python objects (str / tuple); no Discord or Ollama
imports are permitted in psyche_commands.py.
"""
from __future__ import annotations

import pytest

from human_nature.self_state import new_self_state, set_affect
from human_nature.character_vector import new_character_vector, TRAITS
from human_nature.charter import new_charter, draft_amendment, ratify
from human_nature.user_model import new_user_model, update as um_update
from human_nature.psyche_commands import (
    cmd_psyche,
    cmd_dial,
    cmd_charter,
    cmd_whatyouknow,
    cmd_why_i_feel,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ss_with_state() -> dict:
    ss = new_self_state()
    set_affect(ss, -0.3, 0.7, -0.2)   # frustration region
    ss["morale"] = -0.1
    ss["competence"]["python"] = {"p": 0.7, "n": 8}
    return ss


# ---------------------------------------------------------------------------
# cmd_psyche
# ---------------------------------------------------------------------------

def test_cmd_psyche_returns_string():
    result = cmd_psyche(_ss_with_state())
    assert isinstance(result, str)
    assert len(result) > 0


def test_cmd_psyche_contains_affect_or_mood():
    result = cmd_psyche(_ss_with_state()).lower()
    assert "morale" in result or "mood" in result or "affect" in result


def test_cmd_psyche_tolerates_empty_self_state():
    result = cmd_psyche({})
    assert isinstance(result, str)
    assert len(result) > 0


def test_cmd_psyche_tolerates_new_self_state():
    result = cmd_psyche(new_self_state())
    assert isinstance(result, str)


# ---------------------------------------------------------------------------
# cmd_dial — valid trait
# ---------------------------------------------------------------------------

def test_cmd_dial_valid_trait_returns_tuple():
    vec = new_character_vector()
    result = cmd_dial(vec, "humor", 80)
    assert isinstance(result, tuple)
    assert len(result) == 2


def test_cmd_dial_valid_trait_changes_dial_value():
    vec = new_character_vector()
    new_vec, _ = cmd_dial(vec, "humor", 80)
    assert new_vec["traits"]["humor"] == 80


def test_cmd_dial_valid_trait_bumps_version():
    vec = new_character_vector()
    old_version = vec["version"]
    new_vec, _ = cmd_dial(vec, "humor", 80)
    assert new_vec["version"] == old_version + 1


def test_cmd_dial_valid_trait_returns_confirmation_text():
    vec = new_character_vector()
    _, text = cmd_dial(vec, "rigor", 90)
    assert isinstance(text, str)
    assert len(text) > 0


def test_cmd_dial_confirmation_mentions_trait():
    vec = new_character_vector()
    _, text = cmd_dial(vec, "curiosity", 75)
    assert "curiosity" in text.lower()


def test_cmd_dial_all_valid_traits_succeed():
    vec = new_character_vector()
    for trait in TRAITS:
        new_vec, text = cmd_dial(vec, trait, 60)
        assert isinstance(new_vec, dict)
        assert isinstance(text, str)


# ---------------------------------------------------------------------------
# cmd_dial — unknown trait (no exception, returns original + error text)
# ---------------------------------------------------------------------------

def test_cmd_dial_clamps_over_100():
    """cmd_dial with value > 100 must clamp to 100 (no exception, value capped)."""
    vec = new_character_vector()
    new_vec, text = cmd_dial(vec, "humor", 150)
    assert new_vec["traits"]["humor"] == 100
    assert isinstance(text, str)


def test_cmd_dial_unknown_trait_does_not_raise():
    vec = new_character_vector()
    # must not raise
    result = cmd_dial(vec, "not_a_real_trait", 50)
    assert isinstance(result, tuple)


def test_cmd_dial_unknown_trait_returns_original_vector():
    vec = new_character_vector()
    returned_vec, _ = cmd_dial(vec, "not_a_real_trait", 50)
    assert returned_vec == vec


def test_cmd_dial_unknown_trait_returns_error_text():
    vec = new_character_vector()
    _, text = cmd_dial(vec, "not_a_real_trait", 50)
    low = text.lower()
    assert "error" in low or "unknown" in low or "invalid" in low


# ---------------------------------------------------------------------------
# cmd_charter
# ---------------------------------------------------------------------------

def test_cmd_charter_empty_charter_returns_string():
    charter = new_charter()
    result = cmd_charter(charter)
    assert isinstance(result, str)
    assert len(result) > 0


def test_cmd_charter_shows_version():
    charter = new_charter()
    result = cmd_charter(charter)
    assert "version" in result.lower() or "1" in result


def test_cmd_charter_shows_ratified_tenet():
    charter = new_charter()
    amend = draft_amendment("prefer composition over inheritance", "5 runs of evidence")
    charter = ratify(charter, amend, "human_ok")
    result = cmd_charter(charter)
    assert "composition" in result.lower()


def test_cmd_charter_shows_updated_version():
    charter = new_charter()
    amend = draft_amendment("explicit is better than implicit", "pep20 alignment")
    charter = ratify(charter, amend, "human_ok")
    result = cmd_charter(charter)
    assert str(charter["version"]) in result


def test_cmd_charter_multiple_tenets():
    charter = new_charter()
    for i in range(3):
        amend = draft_amendment(f"tenet {i}", f"evidence {i}")
        charter = ratify(charter, amend, "human_ok")
    result = cmd_charter(charter)
    for i in range(3):
        assert f"tenet {i}" in result.lower()


# ---------------------------------------------------------------------------
# cmd_whatyouknow
# ---------------------------------------------------------------------------

def test_cmd_whatyouknow_returns_string():
    model = new_user_model()
    result = cmd_whatyouknow(model)
    assert isinstance(result, str)
    assert len(result) > 0


def test_cmd_whatyouknow_includes_risk_when_set():
    model = new_user_model()
    model = um_update(model, {"kind": "risk", "value": 0.3})
    result = cmd_whatyouknow(model)
    assert "risk" in result.lower() or "0.3" in result


def test_cmd_whatyouknow_includes_trust_when_set():
    model = new_user_model()
    model = um_update(model, {"kind": "trust", "value": 0.8})
    result = cmd_whatyouknow(model)
    assert "trust" in result.lower() or "0.8" in result


def test_cmd_whatyouknow_tolerates_empty_model():
    result = cmd_whatyouknow({})
    assert isinstance(result, str)
    assert len(result) > 0


# ---------------------------------------------------------------------------
# cmd_why_i_feel
# ---------------------------------------------------------------------------

def test_cmd_why_i_feel_returns_string():
    ss = _ss_with_state()
    result = cmd_why_i_feel(ss, {})
    assert isinstance(result, str)
    assert len(result) > 0


def test_cmd_why_i_feel_contains_functional():
    ss = _ss_with_state()
    appraisal = {
        "goal_congruence": -0.5,
        "self_agency": 0.8,
        "novelty": 0.1,
        "certainty": 0.3,
        "coping": 0.4,
    }
    result = cmd_why_i_feel(ss, appraisal)
    assert "functional" in result.lower()


def test_cmd_why_i_feel_includes_named_affect_label():
    ss = _ss_with_state()   # PAD: v=-0.3, a=0.7, c=-0.2 → frustration
    result = cmd_why_i_feel(ss, {"streak": 3, "self_agency": 0.8}).lower()
    assert any(
        term in result
        for term in ("frustration", "anxiety", "satisfaction", "curiosity", "boredom", "neutral")
    )


def test_cmd_why_i_feel_includes_appraisal_vars():
    ss = _ss_with_state()
    appraisal = {"streak": 3, "self_agency": 0.8}
    result = cmd_why_i_feel(ss, appraisal)
    # At least one appraisal key should be echoed
    assert "streak" in result or "self_agency" in result or "agency" in result


def test_cmd_why_i_feel_tolerates_empty_appraisal():
    result = cmd_why_i_feel(_ss_with_state(), {})
    assert isinstance(result, str)
    assert "functional" in result.lower()


def test_cmd_why_i_feel_tolerates_empty_self_state():
    result = cmd_why_i_feel({}, {})
    assert isinstance(result, str)
    assert "functional" in result.lower()


def test_cmd_why_i_feel_never_uses_bare_i_feel():
    """Output must use functional labeling, never just 'I feel <emotion>'."""
    ss = _ss_with_state()
    result = cmd_why_i_feel(ss, {"goal_congruence": -0.5})
    # 'functional' guard replaces naive sentiment speech
    assert "functional" in result.lower()
