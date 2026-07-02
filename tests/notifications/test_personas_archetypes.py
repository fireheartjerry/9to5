"""Tests for Phase 5.1 — sci-fi archetype personas (Data, TARS, Jarvis).

Verifies additive additions to CAST do not regress existing personas and that
the new ARCHETYPES constant is correctly defined.
"""
from __future__ import annotations

import pytest
from notifications.personas import ARCHETYPES, CAST, persona


# ---------------------------------------------------------------------------
# New archetype personas
# ---------------------------------------------------------------------------

def test_data_persona_resolves_with_correct_name():
    p = persona("data")
    assert p["name"] == "Nightclaw · Data"


def test_data_persona_has_avatar_url():
    p = persona("data")
    assert "avatar_url" in p


def test_tars_persona_resolves_with_correct_name():
    p = persona("tars")
    assert p["name"] == "Nightclaw · TARS"


def test_tars_persona_has_avatar_url():
    p = persona("tars")
    assert "avatar_url" in p


def test_jarvis_persona_resolves_with_correct_name():
    p = persona("jarvis")
    assert p["name"] == "Nightclaw · Jarvis"


def test_jarvis_persona_has_avatar_url():
    p = persona("jarvis")
    assert "avatar_url" in p


# ---------------------------------------------------------------------------
# ARCHETYPES constant
# ---------------------------------------------------------------------------

def test_archetypes_contains_three_roles():
    assert len(ARCHETYPES) == 3


def test_archetypes_contains_expected_keys():
    assert set(ARCHETYPES) == {"data", "tars", "jarvis"}


# ---------------------------------------------------------------------------
# Existing personas unchanged (regression)
# ---------------------------------------------------------------------------

_ORIGINAL_ENTRIES = {
    "brain":        "Nightclaw · Brain",
    "orchestrator": "Nightclaw · Brain",
    "architect":    "Nightclaw · Architect",
    "planner":      "Nightclaw · Planner",
    "executor":     "Nightclaw · Executor",
    "verifier":     "Nightclaw · Verifier",
    "adversary":    "Nightclaw · Adversary",
    "replanner":    "Nightclaw · Replanner",
}


@pytest.mark.parametrize("role,expected_name", list(_ORIGINAL_ENTRIES.items()))
def test_original_role_name_unchanged(role: str, expected_name: str):
    p = persona(role)
    assert p["name"] == expected_name


@pytest.mark.parametrize("role", list(_ORIGINAL_ENTRIES))
def test_original_role_has_avatar_url(role: str):
    p = persona(role)
    assert "avatar_url" in p


def test_brain_fallback_still_works():
    """Unknown roles still fall back to brain."""
    p = persona("not_a_real_role")
    assert p["name"] == "Nightclaw · Brain"
