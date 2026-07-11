from learning.outcome_evaluation import EvaluationSuite, EvaluationTask, run_disposable_evaluation
from platform_core.simulator.testing.outcome_runner import run_builder_lifecycle, run_live_lifecycle


def test_builder_lifecycle_runs_planner_executor_verifier_and_review_in_a_worktree(tmp_path):
    import subprocess
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "README.md").write_text("fixture", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture"], check=True, capture_output=True)
    suite = EvaluationSuite("smoke-v1", (EvaluationTask("builder", "feature", "build a tiny feature", {}),))
    result = run_disposable_evaluation("builder-sim", suite, tmp_path, run_builder_lifecycle)
    assert result.receipts[0].passed, result.receipts[0]
    assert result.receipts[0].actual_mode == "simulated"


def test_live_runner_is_explicitly_gated(monkeypatch, tmp_path):
    monkeypatch.delenv("NINE_TO_FIVE_ALLOW_LIVE_OUTCOME_EVALUATION", raising=False)
    result = run_live_lifecycle(EvaluationTask("live", "bugfix", "do", {}), tmp_path)
    assert result["actual_mode"] == "unavailable"


def test_live_runner_rejects_an_unknown_council_mode(monkeypatch, tmp_path):
    monkeypatch.setenv("NINE_TO_FIVE_ALLOW_LIVE_OUTCOME_EVALUATION", "1")
    monkeypatch.setenv("NINE_TO_FIVE_LIVE_OUTCOME_COUNCIL_MODE", "everything")
    result = run_live_lifecycle(EvaluationTask("live", "bugfix", "do", {}), tmp_path)
    assert result["actual_mode"] == "unavailable"
    assert "must be off, advisory, or risk_gate" in result["detail"]


def test_disposable_lifecycle_receipt_rejects_edits_outside_allowed_scope(tmp_path):
    import subprocess

    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "allowed.py").write_text("base", encoding="utf-8")
    (tmp_path / "outside.py").write_text("base", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "."], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-m", "base"], check=True, capture_output=True)
    task = EvaluationTask("scope", "bugfix", "do", {}, allowed_paths=("allowed.py",))

    def lifecycle(_task, workspace):
        (workspace / "outside.py").write_text("changed", encoding="utf-8")
        return {"passed": True, "semantic_passed": True, "actual_mode": "live"}

    result = run_disposable_evaluation("scope", EvaluationSuite("v1", (task,)), tmp_path, lifecycle)
    assert result.receipts[0].passed is False
    assert result.receipts[0].policy_violations == ("outside allowed scope: outside.py",)
