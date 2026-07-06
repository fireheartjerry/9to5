"""Tests for human_nature.consolidation — the sleep/consolidation cycle.

TDD for Phase 4.4. All Ollama calls are mocked via the autouse conftest fixtures;
chat is injectable. No writes to the real state/.
"""
from __future__ import annotations

from pathlib import Path

from human_nature.self_state import get_competence, new_self_state
from human_nature.consolidation import run_cycle, propose_updates


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_chat(reply: str):
    """Fake chat that records call count and returns a response dict."""
    calls: list[int] = [0]

    def _chat(system: str, user: str):  # noqa: ARG001
        calls[0] += 1
        return {"message": {"content": reply}}

    _chat.calls = calls  # type: ignore[attr-defined]
    return _chat


# ---------------------------------------------------------------------------
# Competence update
# ---------------------------------------------------------------------------

def test_scored_judgments_update_competence():
    ss = new_self_state()
    scored = [
        {"domain": "async", "correct": True},
        {"domain": "async", "correct": False},
    ]
    result = run_cycle(ss, scored, [], chat=None)
    c = get_competence(ss, "async")
    assert c["n"] == 2
    assert abs(c["p"] - 0.5) < 1e-9
    assert "async" in result["competence_updated"]


def test_multiple_domains_updated():
    ss = new_self_state()
    scored = [
        {"domain": "async", "correct": True},
        {"domain": "testing", "correct": False},
    ]
    result = run_cycle(ss, scored, [], chat=None)
    assert "async" in result["competence_updated"]
    assert "testing" in result["competence_updated"]
    assert get_competence(ss, "async")["n"] == 1
    assert get_competence(ss, "testing")["n"] == 1


def test_empty_judgments_returns_empty_updated():
    ss = new_self_state()
    result = run_cycle(ss, [], [], chat=None)
    assert result["competence_updated"] == []


# ---------------------------------------------------------------------------
# Counterfactual reflection
# ---------------------------------------------------------------------------

def test_counterfactual_uses_injected_chat():
    ss = new_self_state()
    chat = _make_chat("I would have written the tests first.")
    result = run_cycle(ss, [], ["good run", "slow iteration"], chat=chat)
    assert result["counterfactual"] == "I would have written the tests first."
    assert chat.calls[0] == 1


def test_counterfactual_empty_when_chat_none():
    ss = new_self_state()
    result = run_cycle(ss, [], ["some reflection"], chat=None)
    assert result["counterfactual"] == ""


def test_counterfactual_empty_when_no_reflections_and_chat_none():
    ss = new_self_state()
    result = run_cycle(ss, [], [], chat=None)
    assert result["counterfactual"] == ""


def test_counterfactual_graceful_on_chat_exception():
    """If chat raises, counterfactual degrades to '' rather than crashing."""
    ss = new_self_state()

    def bad_chat(s, u):
        raise RuntimeError("ollama down")

    result = run_cycle(ss, [], ["some reflection"], chat=bad_chat)
    assert result["counterfactual"] == ""


# ---------------------------------------------------------------------------
# Amendment proposals (propose-only, never ratified)
# ---------------------------------------------------------------------------

def test_proposals_all_status_proposed():
    ss = new_self_state()
    reflections = [
        "use composition over inheritance",
        "composition pattern worked well again",
    ]
    result = run_cycle(ss, [], reflections, chat=None)
    assert len(result["proposals"]) > 0
    for p in result["proposals"]:
        assert p["status"] == "proposed"


def test_proposals_never_ratified():
    ss = new_self_state()
    reflections = [
        "prefer small diffs for safety",
        "small diffs caught the regression early",
    ]
    result = run_cycle(ss, [], reflections, chat=None)
    for p in result["proposals"]:
        assert p["status"] != "ratified"


def test_no_proposals_for_empty_reflections():
    ss = new_self_state()
    result = run_cycle(ss, [], [], chat=None)
    assert result["proposals"] == []


def test_proposals_have_required_keys():
    ss = new_self_state()
    reflections = ["test driven wins", "test driven pays off"]
    result = run_cycle(ss, [], reflections, chat=None)
    if result["proposals"]:
        for p in result["proposals"]:
            assert "id" in p
            assert "text" in p
            assert "evidence" in p
            assert "status" in p


# ---------------------------------------------------------------------------
# Practice schedule
# ---------------------------------------------------------------------------

def test_practice_lists_low_p_domains():
    ss = new_self_state()
    scored = [{"domain": "async", "correct": False}]
    result = run_cycle(ss, scored, [], chat=None)
    # async: p=0.0, n=1 -> both below thresholds -> in practice
    assert "async" in result["practice"]


def test_practice_lists_uncertain_domains():
    """n < 5 = high self-uncertainty, should appear in practice."""
    ss = new_self_state()
    scored = [{"domain": "new_skill", "correct": True}]  # n=1 after update
    result = run_cycle(ss, scored, [], chat=None)
    assert "new_skill" in result["practice"]


def test_practice_excludes_confident_domains():
    """Domain with p >= 0.5 and n >= 5 should NOT appear in practice."""
    ss = new_self_state()
    # Seed a domain with many successes directly
    for _ in range(6):
        from human_nature.self_state import observe_competence
        observe_competence(ss, "senior_skill", True)
    result = run_cycle(ss, [], [], chat=None)
    assert "senior_skill" not in result["practice"]


def test_practice_empty_when_no_competence_data():
    ss = new_self_state()
    result = run_cycle(ss, [], [], chat=None)
    assert result["practice"] == []


# ---------------------------------------------------------------------------
# Return shape
# ---------------------------------------------------------------------------

def test_return_keys_complete():
    ss = new_self_state()
    result = run_cycle(ss, [], [], chat=None)
    assert set(result.keys()) >= {"competence_updated", "counterfactual", "proposals", "practice"}


# ---------------------------------------------------------------------------
# propose_updates — pure, propose-not-apply psyche updates from run evidence
# ---------------------------------------------------------------------------

def test_propose_updates_empty_evidence_returns_empty():
    assert propose_updates({}) == []


def test_propose_updates_overconfidence_raises_caution():
    proposals = propose_updates({"repeated_overconfidence": True})
    assert len(proposals) == 1
    p = proposals[0]
    assert p["kind"] == "personality"
    assert p["target"] == "caution"
    assert p["status"] == "proposed"
    assert p["value"] > 0  # raising caution, not lowering it
    assert "rationale" in p and p["rationale"]


def test_propose_updates_low_curiosity_satisfaction_raises_drive_setpoint():
    proposals = propose_updates({"low_curiosity_satisfaction": True})
    assert len(proposals) == 1
    p = proposals[0]
    assert p["kind"] == "drive_setpoint"
    assert p["target"] == "curiosity"
    assert p["status"] == "proposed"
    assert p["value"] > 0


def test_propose_updates_disconfirmed_scars_yields_one_per_scar():
    proposals = propose_updates({"disconfirmed_scars": ["m1", "m2"]})
    assert len(proposals) == 2
    scar_kinds = [p["kind"] for p in proposals]
    scar_targets = [p["target"] for p in proposals]
    assert scar_kinds == ["scar_decay", "scar_decay"]
    assert scar_targets == ["m1", "m2"]
    for p in proposals:
        assert p["status"] == "proposed"


def test_propose_updates_empty_scars_list_yields_nothing():
    assert propose_updates({"disconfirmed_scars": []}) == []


def test_propose_updates_values_bounded():
    proposals = propose_updates({
        "repeated_overconfidence": True,
        "low_curiosity_satisfaction": True,
        "disconfirmed_scars": ["m1"],
    })
    for p in proposals:
        assert -1.0 <= p["value"] <= 1.0


def test_propose_updates_combines_all_signals():
    evidence = {
        "repeated_overconfidence": True,
        "low_curiosity_satisfaction": True,
        "disconfirmed_scars": ["m1", "m2"],
    }
    proposals = propose_updates(evidence)
    assert len(proposals) == 4
    assert all(p["status"] == "proposed" for p in proposals)


def test_propose_updates_never_applies_anything():
    """Pure function: calling it never mutates the evidence dict or any state."""
    evidence = {"repeated_overconfidence": True, "disconfirmed_scars": ["m1"]}
    snapshot = dict(evidence)
    propose_updates(evidence)
    assert evidence == snapshot


def test_propose_updates_idempotent():
    evidence = {
        "repeated_overconfidence": True,
        "low_curiosity_satisfaction": True,
        "disconfirmed_scars": ["m1", "m2"],
    }
    first = propose_updates(evidence)
    second = propose_updates(evidence)
    assert first == second
