"""Tests for human_nature.user_model — Theory-of-Mind of the user (dyad).

TDD for Phase 4.6. Service-only; manipulation-guarded. No real Ollama/Discord.
"""
from __future__ import annotations

import copy
import re

import human_nature.user_model as um
from human_nature.user_model import new_user_model, snapshot, update


# ---------------------------------------------------------------------------
# new_user_model
# ---------------------------------------------------------------------------

def test_new_user_model_defaults():
    m = new_user_model()
    assert m["prefs"] == {}
    assert m["risk_tolerance"] == 0.5
    assert m["attention"] == "unknown"
    assert m["trust"] == 0.5
    assert m["observations"] == []


# ---------------------------------------------------------------------------
# update — immutability
# ---------------------------------------------------------------------------

def test_update_does_not_mutate_input():
    m = new_user_model()
    original = copy.deepcopy(m)
    update(m, {"kind": "risk", "value": 0.8})
    assert m == original


def test_update_returns_new_dict():
    m = new_user_model()
    m2 = update(m, {"kind": "risk", "value": 0.8})
    assert m2 is not m


# ---------------------------------------------------------------------------
# update — observation folding
# ---------------------------------------------------------------------------

def test_update_folds_risk_observation():
    m = new_user_model()
    m2 = update(m, {"kind": "risk", "value": 0.8})
    assert m2["risk_tolerance"] == 0.8


def test_update_folds_attention_observation():
    m = new_user_model()
    m2 = update(m, {"kind": "attention", "value": "present"})
    assert m2["attention"] == "present"


def test_update_folds_trust_observation():
    m = new_user_model()
    m2 = update(m, {"kind": "trust", "value": 0.9})
    assert m2["trust"] == 0.9


def test_update_folds_pref_observation():
    m = new_user_model()
    m2 = update(m, {"kind": "pref", "key": "verbosity", "value": "low"})
    assert m2["prefs"]["verbosity"] == "low"


def test_update_appends_to_observations():
    m = new_user_model()
    m2 = update(m, {"kind": "risk", "value": 0.7})
    assert len(m2["observations"]) == 1
    assert m2["observations"][0] == {"kind": "risk", "value": 0.7}


def test_update_accumulates_observations():
    m = new_user_model()
    for i in range(5):
        m = update(m, {"kind": "risk", "value": float(i) / 10})
    assert len(m["observations"]) == 5


# ---------------------------------------------------------------------------
# update — bounded observations (last 50)
# ---------------------------------------------------------------------------

def test_observations_bounded_at_50():
    m = new_user_model()
    for i in range(60):
        m = update(m, {"kind": "attention", "value": f"state_{i}"})
    assert len(m["observations"]) == 50
    # Should keep the LAST 50
    assert m["observations"][-1]["value"] == "state_59"
    assert m["observations"][0]["value"] == "state_10"


def test_observations_exactly_50_is_not_trimmed():
    m = new_user_model()
    for i in range(50):
        m = update(m, {"kind": "trust", "value": 0.5})
    assert len(m["observations"]) == 50


# ---------------------------------------------------------------------------
# snapshot
# ---------------------------------------------------------------------------

def test_snapshot_returns_all_fields():
    m = new_user_model()
    m = update(m, {"kind": "risk", "value": 0.9})
    s = snapshot(m)
    assert "prefs" in s
    assert "risk_tolerance" in s
    assert "attention" in s
    assert "trust" in s
    assert "observations" in s


def test_snapshot_reflects_current_values():
    m = new_user_model()
    m = update(m, {"kind": "attention", "value": "away"})
    s = snapshot(m)
    assert s["attention"] == "away"


def test_snapshot_does_not_mutate_model():
    m = new_user_model()
    m_copy = copy.deepcopy(m)
    s = snapshot(m)
    s["prefs"]["injected"] = "hack"
    assert m == m_copy  # original unchanged


def test_snapshot_is_fully_inspectable():
    """snapshot() should expose everything needed for !whatyouknow."""
    m = new_user_model()
    m = update(m, {"kind": "pref", "key": "tone", "value": "terse"})
    m = update(m, {"kind": "trust", "value": 0.75})
    s = snapshot(m)
    assert s["prefs"]["tone"] == "terse"
    assert s["trust"] == 0.75
    assert len(s["observations"]) == 2


# ---------------------------------------------------------------------------
# _prefs degradation (absent on this branch → in-memory only)
# ---------------------------------------------------------------------------

def test_prefs_module_unavailable_degrades_gracefully():
    """On this branch memory.user_prefs doesn't exist; _prefs must be None."""
    assert um._prefs is None


def test_operations_work_without_prefs():
    """All operations succeed with _prefs=None (in-memory only)."""
    m = new_user_model()
    m2 = update(m, {"kind": "risk", "value": 0.6})
    s = snapshot(m2)
    assert s["risk_tolerance"] == 0.6


# ---------------------------------------------------------------------------
# Manipulation guard — no public callable suggests timing/persuasion
# ---------------------------------------------------------------------------

_MANIPULATION_PATTERN = re.compile(
    r"time|persuad|manipulat|interrupt|nudge",
    re.IGNORECASE,
)


def test_no_manipulative_public_callables():
    """The module must expose NO public callable whose name suggests manipulation.

    Iterates dir(module), filters to non-private callables (no leading '_'),
    and asserts none match the manipulation pattern (F6 guard).
    """
    public_callables = [
        name for name in dir(um)
        if not name.startswith("_") and callable(getattr(um, name))
    ]
    violations = [n for n in public_callables if _MANIPULATION_PATTERN.search(n)]
    assert violations == [], (
        f"Manipulative public callables found in user_model: {violations}"
    )


def test_public_functions_are_exactly_three():
    """Public functions in user_model must be EXACTLY {new_user_model, update, snapshot}.

    Uses inspect to restrict to functions defined in this module (excludes
    re-exports, imported helpers, timing/persuasion leaks, etc.).
    """
    import inspect
    funcs = {
        name for name, obj in inspect.getmembers(um, inspect.isfunction)
        if not name.startswith("_") and obj.__module__ == um.__name__
    }
    assert funcs == {"new_user_model", "update", "snapshot"}
