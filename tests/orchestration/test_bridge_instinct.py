"""Tests for platform_core/orchestration/human_nature_bridge/instinct.py.

instinctCheck scans a run's event log for dangerous motif PREFIXES/exact matches and,
when found, surfaces a structured InstinctSignal (gated on HUMAN_NATURE_ENABLED and
HN_INSTINCT, best-effort, advisory-only additive action -- it must never touch a
verifier verdict).
"""
from __future__ import annotations

import config
from human_nature.run_events import new_event_log, record_event


def _log(*etypes: str) -> list:
    log = new_event_log()
    for etype in etypes:
        record_event(log, etype)
    return log


def test_instinct_check_off_returns_none_and_writes_nothing(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import instinct as inst

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", False)
    monkeypatch.setattr(config, "HN_INSTINCT", True)
    state = {"meta": {"hn_event_log": _log("PATCH_LARGE", "TESTS_SKIPPED", "CONFIDENCE_HIGH")}}

    assert inst.instinctCheck(state, None) is None
    assert "hn_instinct" not in state["meta"]


def test_instinct_check_off_when_hn_instinct_flag_disabled(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import instinct as inst

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_INSTINCT", False)
    state = {"meta": {"hn_event_log": _log("PATCH_LARGE", "TESTS_SKIPPED", "CONFIDENCE_HIGH")}}

    assert inst.instinctCheck(state, None) is None
    assert "hn_instinct" not in state["meta"]


def test_instinct_check_matches_prefix_and_records(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import instinct as inst

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_INSTINCT", True)
    monkeypatch.setattr(config, "HN_SCAR_MATCH_THRESHOLD", 0.5)
    # A prefix of scar.large-diff-hidden-regression: ["PATCH_LARGE","TESTS_SKIPPED","CONFIDENCE_HIGH"]
    state = {"meta": {"hn_event_log": _log("PATCH_LARGE", "TESTS_SKIPPED")}}

    result = inst.instinctCheck(state, None)

    assert result is not None
    assert result["signal"]["motif_id"] == "scar.large-diff-hidden-regression"
    assert result["signal"]["match_type"] == "prefix"
    assert result["signal"]["recommended_action"] == "deepen_verification"
    assert result["signal"]["authority_request"] == "hold"
    assert state["meta"]["hn_instinct"] == [result]


def test_instinct_check_matches_exact_full_motif(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import instinct as inst

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_INSTINCT", True)
    monkeypatch.setattr(config, "HN_SCAR_MATCH_THRESHOLD", 0.5)
    state = {"meta": {"hn_event_log": _log("PATCH_LARGE", "TESTS_SKIPPED", "CONFIDENCE_HIGH")}}

    result = inst.instinctCheck(state, None)

    assert result is not None
    assert result["signal"]["match_type"] == "exact"
    assert result["signal"]["confidence"] == 1.0
    assert result["signal"]["recommended_action"] == "deepen_verification"


def test_instinct_check_duplicate_signal_is_idempotent(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import instinct as inst

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_INSTINCT", True)
    monkeypatch.setattr(config, "HN_SCAR_MATCH_THRESHOLD", 0.5)
    state = {"meta": {"hn_event_log": _log("PATCH_LARGE", "TESTS_SKIPPED", "CONFIDENCE_HIGH")}}

    first = inst.instinctCheck(state, None)
    second = inst.instinctCheck(state, None)

    assert second == first
    assert state["meta"]["hn_instinct"] == [first]


def test_instinct_check_benign_log_returns_none(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import instinct as inst

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_INSTINCT", True)
    state = {"meta": {"hn_event_log": _log("SUBTASK_STARTED")}}

    assert inst.instinctCheck(state, None) is None
    assert "hn_instinct" not in state["meta"]


def test_instinct_check_surfaces_dashboard_event(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import instinct as inst

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_INSTINCT", True)
    monkeypatch.setattr(config, "HN_SCAR_MATCH_THRESHOLD", 0.5)
    state = {"meta": {"hn_event_log": _log("PATCH_LARGE", "TESTS_SKIPPED")}}
    events = []

    class _Dash:
        def event(self, msg):
            events.append(msg)

    inst.instinctCheck(state, _Dash())

    assert any("instinct" in e for e in events), events


def test_instinct_check_extends_default_motifs_with_meta_scar_motifs(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import instinct as inst

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_INSTINCT", True)
    monkeypatch.setattr(config, "HN_SCAR_MATCH_THRESHOLD", 0.5)
    state = {
        "meta": {
            "hn_event_log": _log("TOOL_TIMEOUT", "OPERATOR_INTERRUPTION"),
            "hn_scar_motifs": [("scar.custom", ["TOOL_TIMEOUT", "OPERATOR_INTERRUPTION", "DIFF_EXPANDING"])],
        }
    }

    result = inst.instinctCheck(state, None)

    assert result is not None
    assert result["signal"]["motif_id"] == "scar.custom"


def test_instinct_check_never_raises_on_malformed_state(monkeypatch):
    from platform_core.orchestration.human_nature_bridge import instinct as inst

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_INSTINCT", True)
    # Malformed meta (not a dict-like the real _meta expects) -> best-effort None.
    assert inst.instinctCheck({"meta": None}, None) is None


def test_instinct_check_never_touches_verifier_verdict(monkeypatch):
    """INVARIANT: instinctCheck only reads the event log; it must never read or alter
    any verifier verdict field, even when a signal fires."""
    from platform_core.orchestration.human_nature_bridge import instinct as inst

    monkeypatch.setattr(config, "HUMAN_NATURE_ENABLED", True)
    monkeypatch.setattr(config, "HN_INSTINCT", True)
    monkeypatch.setattr(config, "HN_SCAR_MATCH_THRESHOLD", 0.5)
    state = {
        "meta": {"hn_event_log": _log("PATCH_LARGE", "TESTS_SKIPPED")},
        "verify_result": {"passed": True, "verdict": "clean"},
    }
    before = dict(state["verify_result"])

    inst.instinctCheck(state, None)

    assert state["verify_result"] == before
