from learning.outcome_evaluation import EvaluationSuite, EvaluationTask, run_outcome_evaluation
from tools.outcome_evaluation_report import render


def test_report_renders_persisted_artifact(tmp_path):
    suite = EvaluationSuite("v1", (EvaluationTask("x", "bugfix", "do", {}),))
    result = run_outcome_evaluation("candidate", suite, lambda task: {"passed": True, "semantic_passed": True}, artifact_dir=tmp_path)
    output = render(result.artifact_path)
    assert "candidate" in output
    assert "bugfix" in output
    assert "insufficient live evidence" in output
    assert "cost=unknown" in output


def test_report_compares_to_persisted_champion(tmp_path):
    suite = EvaluationSuite("v1", (EvaluationTask("x", "bugfix", "do", {}),))
    champion = run_outcome_evaluation("champion", suite, lambda task: {"passed": False}, artifact_dir=tmp_path)
    candidate = run_outcome_evaluation("candidate", suite, lambda task: {"passed": True, "semantic_passed": True}, artifact_dir=tmp_path)
    output = render(candidate.artifact_path, champion.artifact_path)
    assert "Champion comparison:" in output


def test_report_labels_enforced_cost_ceiling_without_faking_spend(tmp_path):
    suite = EvaluationSuite("v1", (EvaluationTask("x", "bugfix", "do", {}, max_cost_usd=2),))
    result = run_outcome_evaluation("candidate", suite, lambda task: {"passed": True, "semantic_passed": True}, artifact_dir=tmp_path)
    assert "cost=unknown; cost ceiling=$2.0000" in render(result.artifact_path)
