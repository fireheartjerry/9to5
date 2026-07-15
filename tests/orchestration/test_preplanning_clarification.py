from __future__ import annotations

from unittest import mock

from agents.planning.preplanning_clarification import (
    PreplanningDecision,
    assessGoal,
)
from platform_core.orchestration.run_phase_mixin import OrchestratorRunPhaseMixin


def test_clear_goal_is_resolved_without_probe() -> None:
    assessment = assessGoal(
        "Add a parser for topology.v1.json and pass tests/platform/test_galaxy_topology.py"
    )
    assert assessment.decision is PreplanningDecision.RESOLVED
    assert assessment.probe is None
    assert assessment.shadow_only is True


def test_vague_goal_proposes_object_only_read_only_probe() -> None:
    assessment = assessGoal("Improve everything and choose the best architecture")
    assert assessment.decision is PreplanningDecision.PROBE_PROPOSED
    assert assessment.score >= 4
    assert assessment.probe is not None
    assert assessment.probe.read_only is True
    assert assessment.probe.object_only is True
    assert assessment.probe.allow_process is False
    assert assessment.probe.allow_network is False
    assert assessment.probe.allow_credentials is False
    assert assessment.probe.authoritative is False


def test_material_high_risk_choice_is_explicitly_blocked_in_shadow_assessment() -> None:
    assessment = assessGoal(
        "Either delete the production database or migrate it; choose whichever auth schema is best"
    )
    assert assessment.decision is PreplanningDecision.BLOCKED
    assert "material-choice" in {signal.name for signal in assessment.signals}
    assert "high-risk" in {signal.name for signal in assessment.signals}


def test_assessment_is_deterministic_and_does_not_retain_goal_text() -> None:
    first = assessGoal("Improve everything")
    second = assessGoal("Improve everything")
    assert first.receipt_id == second.receipt_id
    payload = first.to_dict()
    assert payload["goal_digest"]
    assert "Improve everything" not in repr(payload)


def test_shadow_assessment_runs_before_discovery_and_architect(monkeypatch) -> None:
    call_order: list[str] = []
    state = mock.Mock()
    state.meta = {"goal_raw": "improve everything"}
    dashboard = mock.Mock()
    bus = mock.Mock()

    host = OrchestratorRunPhaseMixin.__new__(OrchestratorRunPhaseMixin)
    host._checkControl = mock.Mock()
    host._runDiscoveryPhase = mock.Mock(
        side_effect=lambda *_args, **_kwargs: call_order.append("discovery")
    )

    def fake_assess(goal: str):
        call_order.append("ambiguity")
        return assessGoal(goal)

    monkeypatch.setattr(
        "agents.planning.preplanning_clarification.assessGoal", fake_assess
    )
    monkeypatch.setattr(
        "agents.architect.authorArchitectPrompt",
        lambda *_args, **_kwargs: call_order.append("architect") or "prompt",
    )
    host._ollamaChat = mock.Mock(return_value="")
    host._run_claude = mock.Mock(side_effect=RuntimeError("stop after architect launch"))
    host._execCwd = mock.Mock(return_value=".")

    try:
        host._freshRunPhase(state, ".", bus, dashboard, "improve everything")
    except RuntimeError as exc:
        assert str(exc) == "stop after architect launch"

    assert call_order[:3] == ["ambiguity", "discovery", "architect"]
    stored = state.meta["galaxy_shadow"]["preplanning_clarification"]
    assert stored["shadow_only"] is True
    assert "goal_digest" in stored
