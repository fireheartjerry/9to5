"""Tests for human_nature/personality.py — versioned PERSONALITY trait vector.

RUN: python -m pytest tests/human_nature/test_personality.py -v
"""
from __future__ import annotations

import copy

import pytest
from human_nature.personality import (
    TRAITS,
    drive_setpoints,
    mood_setpoint,
    new_personality,
    propose_trait,
    ratify,
    risk_band,
)

_DRIVES = (
    "mastery",
    "curiosity",
    "coherence",
    "economy",
    "agency",
    "commitment",
    "integrity",
    "recovery",
)


# ---------------------------------------------------------------------------
# new_personality()
# ---------------------------------------------------------------------------

class TestNewPersonality:
    def test_all_traits_default_to_half(self):
        p = new_personality()
        for trait in TRAITS:
            assert p["traits"][trait] == 0.5

    def test_version_starts_at_1(self):
        assert new_personality()["version"] == 1

    def test_contains_exactly_the_expected_traits(self):
        p = new_personality()
        assert set(p["traits"].keys()) == set(TRAITS)


# ---------------------------------------------------------------------------
# drive_setpoints()
# ---------------------------------------------------------------------------

class TestDriveSetpoints:
    def test_returns_all_eight_drives_in_range(self):
        p = new_personality()
        setpoints = drive_setpoints(p)
        assert set(setpoints.keys()) == set(_DRIVES)
        for name, value in setpoints.items():
            assert 0.0 <= value <= 1.0, f"{name} out of range: {value}"

    def test_curiosity_rises_with_openness(self):
        low = new_personality()
        low["traits"]["openness"] = 0.1
        high = new_personality()
        high["traits"]["openness"] = 0.9
        assert drive_setpoints(high)["curiosity"] > drive_setpoints(low)["curiosity"]

    def test_economy_rises_with_terseness(self):
        low = new_personality()
        low["traits"]["terseness"] = 0.1
        high = new_personality()
        high["traits"]["terseness"] = 0.9
        assert drive_setpoints(high)["economy"] > drive_setpoints(low)["economy"]

    def test_coherence_rises_with_rigor(self):
        low = new_personality()
        low["traits"]["rigor"] = 0.1
        high = new_personality()
        high["traits"]["rigor"] = 0.9
        assert drive_setpoints(high)["coherence"] > drive_setpoints(low)["coherence"]

    def test_agency_rises_with_low_caution(self):
        cautious = new_personality()
        cautious["traits"]["caution"] = 0.9
        bold = new_personality()
        bold["traits"]["caution"] = 0.1
        assert drive_setpoints(bold)["agency"] > drive_setpoints(cautious)["agency"]

    def test_integrity_has_high_baseline(self):
        p = new_personality()
        assert drive_setpoints(p)["integrity"] >= 0.5

    def test_does_not_mutate_input(self):
        p = new_personality()
        snapshot = copy.deepcopy(p)
        drive_setpoints(p)
        assert p == snapshot


# ---------------------------------------------------------------------------
# mood_setpoint()
# ---------------------------------------------------------------------------

class TestMoodSetpoint:
    def test_returns_valence_and_arousal_in_range(self):
        p = new_personality()
        mood = mood_setpoint(p)
        assert set(mood.keys()) == {"valence", "arousal"}
        assert -1.0 <= mood["valence"] <= 1.0
        assert -1.0 <= mood["arousal"] <= 1.0

    def test_valence_rises_with_warmth(self):
        cold = new_personality()
        cold["traits"]["warmth"] = 0.1
        warm = new_personality()
        warm["traits"]["warmth"] = 0.9
        assert mood_setpoint(warm)["valence"] > mood_setpoint(cold)["valence"]

    def test_does_not_mutate_input(self):
        p = new_personality()
        snapshot = copy.deepcopy(p)
        mood_setpoint(p)
        assert p == snapshot


# ---------------------------------------------------------------------------
# risk_band()
# ---------------------------------------------------------------------------

class TestRiskBand:
    def test_in_range(self):
        p = new_personality()
        assert 0.0 <= risk_band(p) <= 1.0

    def test_higher_for_low_caution_high_openness(self):
        cautious = new_personality()
        cautious["traits"]["caution"] = 0.9
        cautious["traits"]["openness"] = 0.1
        bold = new_personality()
        bold["traits"]["caution"] = 0.1
        bold["traits"]["openness"] = 0.9
        assert risk_band(bold) > risk_band(cautious)

    def test_falls_with_rigor(self):
        low_rigor = new_personality()
        low_rigor["traits"]["rigor"] = 0.1
        high_rigor = new_personality()
        high_rigor["traits"]["rigor"] = 0.9
        assert risk_band(low_rigor) > risk_band(high_rigor)

    def test_does_not_mutate_input(self):
        p = new_personality()
        snapshot = copy.deepcopy(p)
        risk_band(p)
        assert p == snapshot


# ---------------------------------------------------------------------------
# propose_trait() — propose-not-apply
# ---------------------------------------------------------------------------

class TestProposeTrait:
    def test_returns_proposal_dict(self):
        p = new_personality()
        proposal = propose_trait(p, "openness", 0.8)
        assert proposal["trait"] == "openness"
        assert proposal["value"] == 0.8
        assert proposal["status"] == "proposed"

    def test_does_not_mutate_input(self):
        p = new_personality()
        snapshot = copy.deepcopy(p)
        propose_trait(p, "openness", 0.8)
        assert p == snapshot

    def test_unknown_trait_raises_valueerror(self):
        p = new_personality()
        with pytest.raises(ValueError, match="unknown trait"):
            propose_trait(p, "nonexistent_trait", 0.5)


# ---------------------------------------------------------------------------
# ratify() — apply a proposal
# ---------------------------------------------------------------------------

class TestRatify:
    def test_applies_trait_value(self):
        p = new_personality()
        proposal = propose_trait(p, "openness", 0.8)
        ratified = ratify(p, proposal)
        assert ratified["traits"]["openness"] == 0.8

    def test_bumps_version(self):
        p = new_personality()
        proposal = propose_trait(p, "openness", 0.8)
        ratified = ratify(p, proposal)
        assert ratified["version"] == 2

    def test_does_not_mutate_input(self):
        p = new_personality()
        snapshot = copy.deepcopy(p)
        proposal = propose_trait(p, "openness", 0.8)
        ratify(p, proposal)
        assert p == snapshot

    def test_rejects_non_proposed_status(self):
        p = new_personality()
        bad_proposal = {"trait": "openness", "value": 0.8, "status": "ratified"}
        with pytest.raises(ValueError, match="not.*proposed|status"):
            ratify(p, bad_proposal)
