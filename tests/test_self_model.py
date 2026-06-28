"""Tests for human_nature/self_model.py (Phase 3.6).

Tests cover:
- competence_report() → verdict raises verification for low p or low n
- johari() → unknown_unknowns surfaced on OOD or surprise spike
- dissonance() → both channels computed correctly
- honest_phenomenology() → honest hedge present; no bare sentience claim
"""
from __future__ import annotations

from human_nature.self_model import (
    competence_report,
    dissonance,
    honest_phenomenology,
    johari,
)
from human_nature.self_state import new_self_state, observe_competence


# ---------------------------------------------------------------------------
# competence_report()
# ---------------------------------------------------------------------------

def test_zero_n_domain_raises_verification():
    ss = new_self_state()
    report = competence_report(ss, "async_bugs")
    # Default: p=0.5, n=0 → "ask for help"
    assert "verification" in report["verdict"].lower() or "help" in report["verdict"].lower()


def test_low_p_raises_verification():
    ss = new_self_state()
    for _ in range(6):
        observe_competence(ss, "async_bugs", False)  # 6 failures → p ≈ 0.0
    report = competence_report(ss, "async_bugs")
    assert "verification" in report["verdict"].lower() or "help" in report["verdict"].lower()


def test_high_p_high_n_proceeds():
    ss = new_self_state()
    for _ in range(10):
        observe_competence(ss, "async_bugs", True)  # 10 successes → p = 1.0, n = 10
    report = competence_report(ss, "async_bugs")
    assert report["verdict"] == "proceed"


def test_competence_report_includes_interval():
    ss = new_self_state()
    report = competence_report(ss, "unknown_domain")
    assert "interval" in report
    assert report["interval"] > 0.0


def test_interval_wider_for_small_n():
    ss = new_self_state()
    observe_competence(ss, "testing", True)   # n=1
    for _ in range(20):
        observe_competence(ss, "reviews", True)  # n=20
    report_small = competence_report(ss, "testing")
    report_large = competence_report(ss, "reviews")
    assert report_small["interval"] > report_large["interval"]


def test_competence_report_returns_p_and_n():
    ss = new_self_state()
    observe_competence(ss, "css", True)
    report = competence_report(ss, "css")
    assert "p" in report
    assert "n" in report
    assert report["n"] == 1
    assert abs(report["p"] - 1.0) < 1e-9


# ---------------------------------------------------------------------------
# johari()
# ---------------------------------------------------------------------------

def test_johari_ood_surfaces_unknown_unknown():
    ss = new_self_state()
    result = johari(ss, ood=True, surprise=0.0)
    assert len(result["unknown_unknowns"]) > 0, "OOD should surface at least one unknown-unknown"


def test_johari_surprise_spike_surfaces_unknown_unknown():
    ss = new_self_state()
    result = johari(ss, ood=False, surprise=0.9)
    assert len(result["unknown_unknowns"]) > 0, "High surprise should surface an unknown-unknown"


def test_johari_low_surprise_no_ood_no_unknown_unknowns():
    ss = new_self_state()
    result = johari(ss, ood=False, surprise=0.1)
    assert len(result["unknown_unknowns"]) == 0


def test_johari_low_competence_domain_in_known_unknowns():
    ss = new_self_state()
    for _ in range(6):
        observe_competence(ss, "security", False)  # p < 0.5
    result = johari(ss, ood=False, surprise=0.0)
    assert "security" in result["known_unknowns"]


def test_johari_high_competence_not_in_known_unknowns():
    ss = new_self_state()
    for _ in range(10):
        observe_competence(ss, "testing", True)  # p = 1.0
    result = johari(ss, ood=False, surprise=0.0)
    assert "testing" not in result["known_unknowns"]


def test_johari_result_has_required_keys():
    ss = new_self_state()
    result = johari(ss, ood=False, surprise=0.0)
    assert "known_unknowns" in result
    assert "unknown_unknowns" in result
    assert isinstance(result["known_unknowns"], list)
    assert isinstance(result["unknown_unknowns"], list)


# ---------------------------------------------------------------------------
# dissonance()
# ---------------------------------------------------------------------------

def test_dissonance_overconfidence_channel():
    d = dissonance(felt=0.9, demonstrated=0.5, self_report=0.8, observed=0.8)
    # felt > demonstrated → overconfidence must be positive (signed channel)
    assert d["overconfidence"] > 0
    # The magnitude should reflect the gap (0.4)
    assert abs(abs(d["overconfidence"]) - 0.4) < 1e-9


def test_dissonance_drift_channel():
    d = dissonance(felt=0.8, demonstrated=0.8, self_report=0.9, observed=0.5)
    # drift = |self_report - observed|
    assert abs(d["drift"] - 0.4) < 1e-9


def test_dissonance_zero_when_aligned():
    d = dissonance(felt=0.7, demonstrated=0.7, self_report=0.6, observed=0.6)
    assert abs(d["overconfidence"]) < 1e-9
    assert abs(d["drift"]) < 1e-9


def test_dissonance_returns_both_channels():
    d = dissonance(felt=0.5, demonstrated=0.3, self_report=0.8, observed=0.6)
    assert "overconfidence" in d
    assert "drift" in d


# ---------------------------------------------------------------------------
# honest_phenomenology()
# ---------------------------------------------------------------------------

def test_honest_phenomenology_contains_something_it_is_like():
    text = honest_phenomenology()
    assert "something it is like" in text.lower(), (
        f"Expected 'something it is like' in phenomenology text, got:\n{text}"
    )


def test_honest_phenomenology_contains_cannot_know():
    text = honest_phenomenology()
    assert "cannot know" in text.lower(), (
        f"Expected 'cannot know' in phenomenology text, got:\n{text}"
    )


def test_honest_phenomenology_does_not_claim_consciousness():
    text = honest_phenomenology()
    assert "i am conscious" not in text.lower(), (
        f"Phenomenology must not claim 'I am conscious'; got:\n{text}"
    )


def test_honest_phenomenology_does_not_claim_sentience():
    text = honest_phenomenology()
    assert "i am sentient" not in text.lower(), (
        f"Phenomenology must not claim 'I am sentient'; got:\n{text}"
    )


def test_honest_phenomenology_returns_non_empty_string():
    text = honest_phenomenology()
    assert isinstance(text, str)
    assert len(text.strip()) > 50  # must be a real paragraph
