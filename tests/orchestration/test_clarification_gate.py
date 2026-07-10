from agents.planning import clarification_gate
from platform_core.orchestration.plan_mixin import OrchestratorPlanMixin


class _State:
    def __init__(self, meta=None):
        self.meta = meta or {}


def test_score_breakdown_enables_self_ref_core_work():
    state = _State({"goal_elaborated": "update executor question handling", "is_self_referential": True})
    sub = {"title": "Executor decision layer", "description": "planner/verifier work", "verify": None}
    out = clarification_gate.scoreAttempt(state, sub, {"effort_level": "xhigh"})
    assert out["decision"] == "force"
    assert out["score"] >= 7
    assert any(s["name"] == "self_referential" for s in out["signals"])


def test_score_skips_clear_mechanical_verified_work():
    state = _State({"goal_elaborated": "fix typo in one file"})
    sub = {"title": "Fix typo", "description": "single file copy typo",
           "verify": {"cmd": "python -m pytest tests/test_docs.py", "expect": "exit_zero"}}
    out = clarification_gate.scoreAttempt(state, sub, {"effort_level": "default"})
    assert out["decision"] == "skip"
    assert any(s["delta"] < 0 for s in out["signals"])


def test_question_policy_only_for_enable_or_force():
    assert clarification_gate.questionPolicyBlock({"decision": "skip"}) == ""
    block = clarification_gate.questionPolicyBlock({"decision": "enable"})
    assert "QUESTION_BLOCK_START" in block
    assert "decision_id" in block
    assert "Should I proceed" in block


def test_flag_off_does_not_modify_spec_shape(monkeypatch):
    monkeypatch.setattr("config.CLARIFICATION_GATE_ENABLED", False, raising=False)
    monkeypatch.setattr("config.CLARIFICATION_GATE_DRY_RUN", False, raising=False)
    host = OrchestratorPlanMixin()
    spec = {"prompt": "Do the thing.", "claude_md_inject": ""}
    out = host._applyClarificationPolicy(_State({"goal_elaborated": "executor work"}), {}, dict(spec))
    assert out == spec


def test_dry_run_scores_without_prompt_injection(monkeypatch):
    monkeypatch.setattr("config.CLARIFICATION_GATE_ENABLED", False, raising=False)
    monkeypatch.setattr("config.CLARIFICATION_GATE_DRY_RUN", True, raising=False)
    host = OrchestratorPlanMixin()
    spec = {"prompt": "Do the thing.", "claude_md_inject": "", "effort_level": "xhigh"}
    out = host._applyClarificationPolicy(
        _State({"goal_elaborated": "executor work", "is_self_referential": True}), {}, dict(spec))
    assert "clarification_gate" in out
    assert "QUESTION_BLOCK_START" not in out["prompt"]


def test_retry_and_context_signals_are_wired(monkeypatch):
    monkeypatch.setattr("config.CLARIFICATION_GATE_ENABLED", True, raising=False)
    monkeypatch.setattr("config.CLARIFICATION_GATE_DRY_RUN", False, raising=False)
    host = OrchestratorPlanMixin()
    spec = {"prompt": "x" * 60001, "claude_md_inject": "", "effort_level": "default"}
    sub = {"title": "Retry task", "description": "ambiguous executor work", "verify": None}
    out = host._applyClarificationPolicy(
        _State({"goal_elaborated": "executor work", "is_self_referential": True}),
        sub,
        spec,
        attempt=2,
    )
    names = {s["name"] for s in out["clarification_gate"]["signals"]}
    assert "retry_attempt" in names
    assert "context_payload_large" in names


def test_readonly_probe_subtask_forces_readonly_executor_spec(monkeypatch):
    monkeypatch.setattr("config.CLARIFICATION_GATE_ENABLED", False, raising=False)
    monkeypatch.setattr("config.CLARIFICATION_GATE_DRY_RUN", False, raising=False)
    host = OrchestratorPlanMixin()
    host._foldOperatorContext = lambda _state, _subtask, spec: spec
    state = _State({"goal_elaborated": "g"})
    spec = host._finalizeInvocationSpec(
        state,
        {"read_only": True, "clarification_probe": True},
        {"prompt": "Inspect the code.", "claude_md_inject": ""},
        None,
    )
    assert spec["read_only"] is True
    assert spec["clarification_probe"] is True
    assert "READ-ONLY EVIDENCE PROBE" in spec["prompt"]
    assert "Do not modify files" in spec["claude_md_inject"]
