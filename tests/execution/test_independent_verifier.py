"""Independent verifier: verdict from an envelope, gating, and a read-only spawn that NEVER auto-passes."""

from agents import completion_envelope as ce
from agents import independent_verifier as iv


def test_verdict_passes_only_when_all_met_and_green():
    env = ce.CompletionEnvelope(
        diff_summary="x", files_changed=["a.py"],
        test_results=[{"command": "pytest", "exit_code": 0}],
        acceptance_criteria_status=[{"criterion": "c", "met": True}], residual_risks=[])
    v = iv.verdictFromEnvelope(env)
    assert v.passed and not v.inconclusive and v.unmet == []


def test_verdict_unmet_criterion_fails():
    env = ce.CompletionEnvelope(
        diff_summary="x", files_changed=["a.py"],
        test_results=[{"command": "pytest", "exit_code": 0}],
        acceptance_criteria_status=[{"criterion": "c", "met": False}], residual_risks=[])
    v = iv.verdictFromEnvelope(env)
    assert not v.passed and v.unmet == ["c"]


def test_no_envelope_is_inconclusive_never_passes():
    v = iv.verdictFromEnvelope(None)
    assert not v.passed and v.inconclusive


def test_no_criteria_is_inconclusive():
    env = ce.CompletionEnvelope("x", ["a.py"], [{"command": "p", "exit_code": 0}], [], [])
    v = iv.verdictFromEnvelope(env)
    assert v.inconclusive and not v.passed


def test_gating_requires_code_change_and_flag():
    assert iv.shouldRunIndependentVerify(enabled=True, has_code_change=True, tree_shared=False)
    assert not iv.shouldRunIndependentVerify(enabled=False, has_code_change=True, tree_shared=False)
    assert not iv.shouldRunIndependentVerify(enabled=True, has_code_change=False, tree_shared=False)
    assert not iv.shouldRunIndependentVerify(enabled=True, has_code_change=True, tree_shared=True)


def test_spawn_crash_is_inconclusive():
    def boom(*a, **k):
        return {"ok": False, "stdout": "", "stderr": "spawn failed"}
    parse = iv.runIndependentVerification(
        boom, goal="g", acceptance_criteria="c", diff_summary="d",
        work_dir=".", task_state=None, subtask={"subtask_id": "st-001"})
    assert parse.present is False  # no envelope => caller treats as inconclusive, never auto-pass
