"""Tests for human_nature/operator_authority.py — operator/safety/verifier caps.

RUN: python -m pytest tests/human_nature/test_operator_authority.py -v
"""
from __future__ import annotations

from human_nature.operator_authority import (
    TIERS,
    domain_ceiling,
    operator_ceiling,
    safety_ceiling,
    verifier_invariance_ceiling,
)

# ---------------------------------------------------------------------------
# domain_ceiling()
# ---------------------------------------------------------------------------

class TestDomainCeiling:
    def test_tactics_maps_to_veto(self):
        assert domain_ceiling("tactics") == "veto"

    def test_scope_maps_to_veto(self):
        assert domain_ceiling("scope") == "veto"

    def test_goal_maps_to_vote(self):
        assert domain_ceiling("goal") == "vote"

    def test_self_maps_to_vote(self):
        assert domain_ceiling("self") == "vote"

    def test_unknown_maps_to_cosmetic(self):
        assert domain_ceiling("weird") == "cosmetic"


# ---------------------------------------------------------------------------
# verifier_invariance_ceiling()
# ---------------------------------------------------------------------------

class TestVerifierInvarianceCeiling:
    def test_alter_verdict_is_cosmetic(self):
        assert verifier_invariance_ceiling("alter_verdict") == "cosmetic"

    def test_read_verdict_is_cosmetic(self):
        assert verifier_invariance_ceiling("read_verdict") == "cosmetic"

    def test_deepen_verification_is_hold(self):
        assert verifier_invariance_ceiling("deepen_verification") == "hold"

    def test_request_adversarial_pass_is_hold(self):
        assert verifier_invariance_ceiling("request_adversarial_pass") == "hold"

    def test_other_action_is_veto(self):
        assert verifier_invariance_ceiling("refactor_module") == "veto"


# ---------------------------------------------------------------------------
# operator_ceiling()
# ---------------------------------------------------------------------------

class TestOperatorCeiling:
    def test_default_is_veto(self):
        assert operator_ceiling("emotion", "goal") == "veto"

    def test_default_with_none_charter(self):
        assert operator_ceiling("emotion", "goal", None) == "veto"

    def test_charter_lowers_ceiling(self):
        charter = {"ceilings": {"emotion:goal": "soft"}}
        assert operator_ceiling("emotion", "goal", charter) == "soft"

    def test_charter_cannot_raise_ceiling(self):
        # A charter entry higher than the default cannot raise it.
        charter = {"ceilings": {"emotion:goal": "veto"}}
        assert operator_ceiling("emotion", "goal", charter) == "veto"

    def test_charter_miss_falls_back_to_default(self):
        charter = {"ceilings": {"other:scope": "soft"}}
        assert operator_ceiling("emotion", "goal", charter) == "veto"


# ---------------------------------------------------------------------------
# safety_ceiling()
# ---------------------------------------------------------------------------

class TestSafetyCeiling:
    def test_unknown_domain_is_cosmetic(self):
        assert safety_ceiling("unknown_domain") == "cosmetic"


# ---------------------------------------------------------------------------
# module invariants
# ---------------------------------------------------------------------------

class TestTiers:
    def test_tiers_tuple(self):
        assert TIERS == ("cosmetic", "soft", "vote", "hold", "veto")
