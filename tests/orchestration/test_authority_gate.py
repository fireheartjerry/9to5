"""Tests for human_nature_bridge.authority_gate.resolveTier -- the 5-cap min resolver."""
from __future__ import annotations

from human_nature import operator_authority
from platform_core.orchestration.human_nature_bridge.authority_gate import resolveTier


def test_verdict_touching_action_resolves_cosmetic():
    """A verdict-touching action is capped at cosmetic by the verifier-invariance ceiling,
    no matter how high the conviction or how strong the track record."""
    tier = resolveTier(
        faculty="intuition",
        domain="tactics",
        conviction=0.99,
        track={"total": 50, "rate": 0.98},
        action="alter_verdict",
    )
    assert tier == "cosmetic"


def test_high_conviction_additive_action_resolves_hold(monkeypatch):
    """High conviction + proven track record + an additive (non-verdict-touching) action
    resolves to the HN_AUTHORITY_MAX default "hold" when safety permits."""
    # The default hard-safety cap floors unknown domains at cosmetic; a deployment that has
    # cleared this domain for safety lifts that cap, exposing the additive-hold / hard-max path.
    monkeypatch.setattr(operator_authority, "safety_ceiling", lambda domain: "veto")
    tier = resolveTier(
        faculty="intuition",
        domain="tactics",
        conviction=0.99,
        track={"total": 50, "rate": 0.98},
        action="deepen_verification",
    )
    assert tier == "hold"


def test_resolve_is_no_op_safe_and_returns_cosmetic_on_error(monkeypatch):
    """Any error inside the resolver is swallowed and yields the weakest tier."""
    def _boom(*a, **k):
        raise RuntimeError("authority down")

    monkeypatch.setattr(operator_authority, "domain_ceiling", _boom)
    assert resolveTier("intuition", "tactics", 0.99, {"total": 50, "rate": 0.98}) == "cosmetic"
