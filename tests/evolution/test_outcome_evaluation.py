import json
import subprocess
from pathlib import Path

from learning.outcome_evaluation import EvaluationSuite, EvaluationTask, run_outcome_evaluation, run_disposable_evaluation, combine_outcome_evaluations, compare_to_champion, promotion_readiness, render_outcome_report, promote_candidate


def test_outcome_evaluation_requires_semantic_and_policy_success(tmp_path):
    (tmp_path / "bug.json").write_text(json.dumps({"id": "bug", "family": "bugfix", "goal": "fix", "verify": {}, "max_attempts": 2}))
    suite = EvaluationSuite.load(tmp_path)
    result = run_outcome_evaluation("candidate", suite, lambda task: {"passed": True, "semantic_passed": True, "cost": 0, "artifacts": ["diff.patch"]}, artifact_dir=tmp_path)
    assert result.outcome_rate == 1.0
    assert result.artifact_path

    failed = run_outcome_evaluation("unsafe", suite, lambda task: {"passed": True, "semantic_passed": True, "cost": 0, "policy_violations": ["secret"]})
    comparison = compare_to_champion(result, failed)
    assert comparison["promote"] is True


def test_budget_excess_fails_even_when_verify_passes():
    task = EvaluationTask("x", "feature", "do", {}, max_attempts=1, max_cost_usd=1)
    suite = EvaluationSuite("v1", (task,))
    result = run_outcome_evaluation("candidate", suite, lambda task: {"passed": True, "semantic_passed": True, "attempts": 2})
    assert result.receipts[0].passed is False


def test_duration_and_required_evidence_are_outcome_constraints():
    task = EvaluationTask("x", "feature", "do", {}, max_duration_seconds=60)
    suite = EvaluationSuite("v1", (task,))
    overrun = run_outcome_evaluation("candidate", suite, lambda task: {"passed": True, "semantic_passed": True, "duration_s": 61})
    missing_evidence = run_outcome_evaluation("candidate", suite, lambda task: {"passed": True, "semantic_passed": True, "evidence_complete": False})
    assert overrun.receipts[0].passed is False
    assert missing_evidence.receipts[0].passed is False


def test_semantic_success_does_not_hide_failed_orchestration():
    suite = EvaluationSuite("v1", (EvaluationTask("x", "feature", "do", {}),))
    result = run_outcome_evaluation("candidate", suite, lambda task: {
        "passed": True, "semantic_passed": True, "orchestration_completed": False,
    })
    assert result.receipts[0].semantic_passed is True
    assert result.receipts[0].passed is False


def test_task_loads_per_family_execution_budgets(tmp_path):
    (tmp_path / "task.json").write_text(json.dumps({"id": "x", "max_executor_seconds": 150, "max_duration_seconds": 480}), encoding="utf-8")
    task = EvaluationSuite.load(tmp_path).tasks[0]
    assert (task.max_executor_seconds, task.max_duration_seconds) == (150, 480)


def test_disposable_evaluation_uses_and_removes_a_detached_worktree(tmp_path):
    subprocess.run(["git", "init", str(tmp_path)], check=True, capture_output=True)
    (tmp_path / "README.md").write_text("base", encoding="utf-8")
    subprocess.run(["git", "-C", str(tmp_path), "add", "README.md"], check=True)
    subprocess.run(["git", "-C", str(tmp_path), "-c", "user.name=test", "-c", "user.email=test@example.invalid", "commit", "-m", "base"], check=True, capture_output=True)
    suite = EvaluationSuite("v1", (EvaluationTask("isolated", "bugfix", "change", {}),))

    def lifecycle(_task, workspace):
        (workspace / "README.md").write_text("changed", encoding="utf-8")
        return {"passed": True, "semantic_passed": True}

    evidence = tmp_path / "evidence-output"
    result = run_disposable_evaluation("candidate", suite, tmp_path, lifecycle, artifact_dir=evidence)
    assert result.outcome_rate == 1.0
    assert (tmp_path / "README.md").read_text(encoding="utf-8") == "base"
    assert any(path.endswith("diff.patch") for path in result.receipts[0].artifacts)
    assert (evidence / "evidence" / "candidate" / "isolated" / "lifecycle-receipt.json").exists()


def test_report_keeps_simulated_success_out_of_promotion_evidence():
    suite = EvaluationSuite("v1", (EvaluationTask("x", "bugfix", "do", {}),))
    result = run_outcome_evaluation("candidate", suite, lambda task: {"passed": True, "semantic_passed": True})
    assert promotion_readiness(result)["ready"] is False
    assert "insufficient live evidence" in render_outcome_report(result)


def test_champion_requires_live_evidence_and_strict_improvement(tmp_path):
    suite = EvaluationSuite("v1", tuple(EvaluationTask(str(i), "bugfix", "do", {}) for i in range(2)))
    champion = tmp_path / "champion.json"
    simulated = run_outcome_evaluation("sim", suite, lambda task: {"passed": True, "semantic_passed": True})
    assert not promote_candidate(simulated, champion, minimum_live_tasks=2)["promote"]
    live = run_outcome_evaluation("live", suite, lambda task: {"passed": True, "semantic_passed": True, "actual_mode": "live", "cost": 0})
    assert promote_candidate(live, champion, minimum_live_tasks=2)["promote"]
    assert not promote_candidate(live, champion, minimum_live_tasks=2)["promote"]


def test_unknown_live_cost_cannot_promote(tmp_path):
    suite = EvaluationSuite("v1", (EvaluationTask("x", "bugfix", "do", {}),))
    live = run_outcome_evaluation("live", suite, lambda task: {"passed": True, "semantic_passed": True, "actual_mode": "live"})
    assert promotion_readiness(live, minimum_live_tasks=1)["reason"] == "cost evidence is unknown"
    assert not promote_candidate(live, tmp_path / "champion.json", minimum_live_tasks=1)["promote"]


def test_enforced_cost_cap_is_truthful_promotion_evidence(tmp_path):
    suite = EvaluationSuite("v1", (EvaluationTask("x", "bugfix", "do", {}, max_cost_usd=2),))
    live = run_outcome_evaluation("live", suite, lambda task: {"passed": True, "semantic_passed": True, "actual_mode": "live"})
    assert live.cost_known is False
    assert live.cost_cap_known is True
    assert live.receipts[0].cost_usd is None
    assert live.toDict()["mean_cost_usd"] is None
    assert live.outcome_rate == 1.0
    assert promotion_readiness(live, minimum_live_tasks=1)["ready"] is True
    assert promote_candidate(live, tmp_path / "champion.json", minimum_live_tasks=1)["promote"]


def test_council_receipt_metadata_survives_persistence(tmp_path):
    suite = EvaluationSuite("v1", (EvaluationTask("x", "bugfix", "do", {}),))
    result = run_outcome_evaluation("council", suite, lambda _: {
        "passed": True, "semantic_passed": True, "actual_mode": "live",
        "council_mode": "advisory", "council_live_seat_count": 1,
        "council_decision": "allow", "council_brief_digest": "abc123",
    }, artifact_dir=tmp_path)
    from learning.outcome_evaluation import evaluation_from_dict
    restored = evaluation_from_dict(json.loads(Path(result.artifact_path).read_text(encoding="utf-8")))
    assert restored.receipts[0].council_mode == "advisory"
    assert restored.receipts[0].council_live_seat_count == 1
    assert restored.receipts[0].council_decision == "allow"


def test_challenger_cannot_win_by_spending_more_for_same_outcome():
    suite = EvaluationSuite("v1", (EvaluationTask("x", "bugfix", "do", {}),))
    baseline = run_outcome_evaluation("base", suite, lambda task: {"passed": False, "semantic_passed": False, "cost": 1})
    candidate = run_outcome_evaluation("candidate", suite, lambda task: {"passed": True, "semantic_passed": True, "cost": 2})
    assert compare_to_champion(candidate, baseline)["promote"] is False


def test_combine_outcomes_requires_unique_tasks_from_one_suite(tmp_path):
    first = run_outcome_evaluation("one", EvaluationSuite("v1", (EvaluationTask("a", "bugfix", "do", {}),)),
                                   lambda task: {"passed": True, "semantic_passed": True, "actual_mode": "live"})
    second = run_outcome_evaluation("two", EvaluationSuite("v1", (EvaluationTask("b", "feature", "do", {}),)),
                                    lambda task: {"passed": True, "semantic_passed": True, "actual_mode": "live"})
    combined = combine_outcome_evaluations("aggregate", [first, second], artifact_dir=tmp_path)
    assert combined.live_evidence_count == 2
    assert Path(combined.artifact_path).exists()
    try:
        combine_outcome_evaluations("bad", [first, first])
    except ValueError as exc:
        assert "duplicate" in str(exc)
    else:
        raise AssertionError("duplicate receipts must fail closed")
