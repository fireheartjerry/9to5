"""Tests for human_nature/character_vector.py — TARS dials.

RUN: python -m pytest tests/test_character_vector.py -v
"""
from __future__ import annotations

import copy

import pytest
from human_nature.character_vector import (
    TRAITS,
    new_character_vector,
    propose_change,
    ratify,
    set_dial,
)


# ---------------------------------------------------------------------------
# new_character_vector()
# ---------------------------------------------------------------------------

class TestNewCharacterVector:
    def test_all_traits_default_to_50(self):
        vec = new_character_vector()
        for trait in TRAITS:
            assert vec["traits"][trait] == 50

    def test_version_starts_at_1(self):
        assert new_character_vector()["version"] == 1

    def test_contains_exactly_the_expected_traits(self):
        vec = new_character_vector()
        assert set(vec["traits"].keys()) == set(TRAITS)


# ---------------------------------------------------------------------------
# set_dial() — human action, returns new dict, does not mutate input
# ---------------------------------------------------------------------------

class TestSetDial:
    def test_sets_trait_value(self):
        vec = new_character_vector()
        vec2 = set_dial(vec, "humor", 75)
        assert vec2["traits"]["humor"] == 75

    def test_bumps_version(self):
        vec = new_character_vector()
        vec2 = set_dial(vec, "humor", 75)
        assert vec2["version"] == 2

    def test_does_not_mutate_input(self):
        vec = new_character_vector()
        original_traits = copy.deepcopy(vec["traits"])
        original_version = vec["version"]
        set_dial(vec, "humor", 75)
        assert vec["traits"] == original_traits
        assert vec["version"] == original_version

    def test_clamps_above_100(self):
        vec = new_character_vector()
        vec2 = set_dial(vec, "sass", 999)
        assert vec2["traits"]["sass"] == 100

    def test_clamps_below_0(self):
        vec = new_character_vector()
        vec2 = set_dial(vec, "sass", -50)
        assert vec2["traits"]["sass"] == 0

    def test_boundary_values_accepted(self):
        vec = new_character_vector()
        assert set_dial(vec, "rigor", 0)["traits"]["rigor"] == 0
        assert set_dial(vec, "rigor", 100)["traits"]["rigor"] == 100

    def test_unknown_trait_raises_valueerror(self):
        vec = new_character_vector()
        with pytest.raises(ValueError, match="unknown trait"):
            set_dial(vec, "nonexistent_trait", 50)

    def test_multiple_set_dials_accumulate_version(self):
        vec = new_character_vector()
        vec2 = set_dial(vec, "honesty", 90)
        vec3 = set_dial(vec2, "curiosity", 80)
        assert vec3["version"] == 3
        assert vec3["traits"]["honesty"] == 90
        assert vec3["traits"]["curiosity"] == 80


# ---------------------------------------------------------------------------
# propose_change() — system action, propose-not-apply (F6)
# ---------------------------------------------------------------------------

class TestProposeChange:
    def test_returns_proposal_dict(self):
        vec = new_character_vector()
        p = propose_change(vec, "curiosity", 80, "keeps paying off in complex tasks")
        assert p["trait"] == "curiosity"
        assert p["value"] == 80
        assert p["rationale"] == "keeps paying off in complex tasks"
        assert p["status"] == "proposed"

    def test_does_not_mutate_vec(self):
        vec = new_character_vector()
        original_traits = copy.deepcopy(vec["traits"])
        original_version = vec["version"]
        propose_change(vec, "curiosity", 80, "test")
        assert vec["traits"] == original_traits
        assert vec["version"] == original_version

    def test_vec_version_unchanged_after_propose(self):
        vec = new_character_vector()
        propose_change(vec, "curiosity", 80, "test")
        assert vec["version"] == 1

    def test_propose_does_not_apply(self):
        vec = new_character_vector()
        propose_change(vec, "humor", 99, "test")
        # value must NOT appear in vec's traits
        assert vec["traits"]["humor"] == 50


# ---------------------------------------------------------------------------
# ratify() — applies a proposal, increments version, returns new vec
# ---------------------------------------------------------------------------

class TestRatify:
    def test_ratify_applies_proposal(self):
        vec = new_character_vector()
        p = propose_change(vec, "caution", 70, "test")
        vec2 = ratify(vec, p)
        assert vec2["traits"]["caution"] == 70

    def test_ratify_bumps_version(self):
        vec = new_character_vector()
        p = propose_change(vec, "caution", 70, "test")
        vec2 = ratify(vec, p)
        assert vec2["version"] == 2

    def test_ratify_does_not_mutate_input(self):
        vec = new_character_vector()
        original = copy.deepcopy(vec)
        p = propose_change(vec, "caution", 70, "test")
        ratify(vec, p)
        assert vec == original

    def test_ratify_clamps_out_of_range_proposal_value(self):
        vec = new_character_vector()
        # Manually craft a proposal with an out-of-range value
        p = {"trait": "formality", "value": 150, "rationale": "test", "status": "proposed"}
        vec2 = ratify(vec, p)
        assert vec2["traits"]["formality"] == 100

    def test_ratify_sets_correct_trait_only(self):
        vec = new_character_vector()
        p = propose_change(vec, "honesty", 95, "test")
        vec2 = ratify(vec, p)
        # All other traits unchanged
        for trait in TRAITS:
            if trait != "honesty":
                assert vec2["traits"][trait] == 50
        assert vec2["traits"]["honesty"] == 95
