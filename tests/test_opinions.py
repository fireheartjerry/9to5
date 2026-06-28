"""Tests for human_nature/opinions.py (Phase 3.2).

Tests cover:
- tier() thresholds × domain ceilings (Q1/Q2)
- rederive() neutral-judge re-derivation with mocked chat (F5)
- Opinion dataclass shape
"""
from __future__ import annotations

import config
from human_nature.opinions import DOMAIN_VETO_CEILING, Opinion, rederive, tier


# ---------------------------------------------------------------------------
# tier — thresholds
# ---------------------------------------------------------------------------

def test_below_soft_is_cosmetic_any_domain():
    assert tier(0.0, "tactics") == "cosmetic"
    assert tier(0.59, "tactics") == "cosmetic"
    assert tier(0.59, "scope") == "cosmetic"


def test_at_soft_threshold_is_soft_for_tactics():
    # conviction == HN_THETA_SOFT (0.60) is NOT < soft, so → soft
    assert tier(config.HN_THETA_SOFT, "tactics") == "soft"


def test_between_soft_and_hard_is_soft_for_tactics():
    assert tier(0.70, "tactics") == "soft"
    assert tier(0.84, "tactics") == "soft"


def test_above_hard_in_tactics_is_hard():
    assert tier(config.HN_THETA_HARD, "tactics") == "hard"
    assert tier(0.99, "tactics") == "hard"


def test_above_hard_in_scope_is_hard():
    assert tier(0.99, "scope") == "hard"


# ---------------------------------------------------------------------------
# tier — domain ceilings (Q2)
# ---------------------------------------------------------------------------

def test_goal_domain_caps_at_soft():
    """D3 goal is sovereign — even 0.99 conviction yields at most soft."""
    assert tier(0.99, "goal") == "soft"
    assert tier(config.HN_THETA_HARD, "goal") == "soft"


def test_self_domain_caps_at_soft():
    """D4 self — always expressed, caps at soft."""
    assert tier(0.99, "self") == "soft"
    assert tier(config.HN_THETA_HARD, "self") == "soft"


def test_unknown_domain_caps_at_cosmetic():
    """Unknown domain: cosmetic ceiling (cold-start safety)."""
    assert tier(0.99, "never_seen") == "cosmetic"
    assert tier(0.70, "something_new") == "cosmetic"
    assert tier(config.HN_THETA_SOFT, "random") == "cosmetic"


def test_domain_veto_ceiling_keys():
    assert DOMAIN_VETO_CEILING["tactics"] == "hard"
    assert DOMAIN_VETO_CEILING["scope"] == "hard"
    assert DOMAIN_VETO_CEILING["goal"] == "soft"
    assert DOMAIN_VETO_CEILING["self"] == "soft"


# ---------------------------------------------------------------------------
# rederive — neutral-judge re-derivation (F5)
# ---------------------------------------------------------------------------

def _make_chat(reply: str):
    """Fake chat that records calls and returns ``reply``."""
    captured: dict = {}

    def _chat(system, user):  # noqa: ARG001
        captured["system"] = system
        captured["user"] = user
        return {"message": {"content": reply}}

    _chat.captured = captured  # type: ignore[attr-defined]
    return _chat


def test_rederive_hold_verdict():
    chat = _make_chat("HOLD: the evidence supports B clearly.")
    result = rederive("A is right", "B is right", "strong evidence for B", chat=chat)
    assert result["verdict"] == "hold"
    assert result["rationale"]


def test_rederive_concede_verdict():
    chat = _make_chat("CONCEDE: A is clearly supported by the evidence provided.")
    result = rederive("A is right", "B is right", "strong evidence for A", chat=chat)
    assert result["verdict"] == "concede"
    assert result["rationale"]


def test_rederive_prompt_includes_both_positions_and_evidence():
    """Judge prompt must contain both stances and the evidence string."""
    chat = _make_chat("HOLD")
    rederive("user_asserts_X", "my_stance_Y", "the_evidence_Z", chat=chat)
    prompt = chat.captured["user"]  # type: ignore[attr-defined]
    assert "user_asserts_X" in prompt
    assert "my_stance_Y" in prompt
    assert "the_evidence_Z" in prompt


def test_rederive_unparseable_with_evidence_holds():
    """Unparseable reply + non-empty evidence → hold (don't capitulate on noise)."""
    chat = _make_chat("I cannot determine the answer from the given information.")
    result = rederive("A", "B", "some real evidence", chat=chat)
    assert result["verdict"] == "hold"


def test_rederive_unparseable_without_evidence_still_holds():
    """Default to hold even when evidence is empty — never capitulate on noise."""
    chat = _make_chat("unclear")
    result = rederive("A", "B", "", chat=chat)
    assert result["verdict"] == "hold"


def test_rederive_case_insensitive_hold():
    chat = _make_chat("hold — evidence is inconclusive")
    result = rederive("A", "B", "some evidence", chat=chat)
    assert result["verdict"] == "hold"


def test_rederive_case_insensitive_concede():
    chat = _make_chat("concede. The data backs A.")
    result = rederive("A", "B", "some evidence", chat=chat)
    assert result["verdict"] == "concede"


# ---------------------------------------------------------------------------
# rederive — F5 anti-capitulation hardening
# ---------------------------------------------------------------------------

def test_rederive_does_not_capitulate_on_hedged_hold():
    """Reply containing both words: HOLD must win (checked first; F5 bias)."""
    def chat(system, user):  # noqa: ARG001
        return {"message": {"content": "Don't CONCEDE, HOLD the position"}}

    out = rederive("ship it now", "add a test first", "the module has zero coverage", chat=chat)
    assert out["verdict"] == "hold"


def test_rederive_never_concedes_without_evidence():
    """Empty evidence forces hold regardless of model reply (F5/F4 guard)."""
    def chat(system, user):  # noqa: ARG001
        return {"message": {"content": "CONCEDE"}}

    out = rederive("ship it now", "add a test first", "", chat=chat)
    assert out["verdict"] == "hold"


def test_rederive_system_prompt_is_neutral():
    """Judge system prompt must contain 'neutral' so neither position is pre-favoured."""
    captured: dict = {}

    def chat(system, user):
        captured["system"] = system
        captured["user"] = user
        return {"message": {"content": "HOLD: evidence supports B"}}

    rederive("A", "B", "some evidence", chat=chat)
    assert "neutral" in captured["system"].lower()


# ---------------------------------------------------------------------------
# Opinion dataclass
# ---------------------------------------------------------------------------

def test_opinion_dataclass_fields():
    op = Opinion(text="prefer composition", domain="tactics", conviction=0.9)
    assert op.text == "prefer composition"
    assert op.domain == "tactics"
    assert op.conviction == 0.9
