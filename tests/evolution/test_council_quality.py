from learning.council_quality import compare_council_impact
from learning.outcome_evaluation import EvaluationSuite, EvaluationTask, run_outcome_evaluation


def _evaluation(name, *, passed, replans=0, catches=0, cost=1):
    suite = EvaluationSuite("v1", tuple(EvaluationTask(str(i), "bugfix", "do", {}) for i in range(8)))
    return run_outcome_evaluation(name, suite, lambda task: {
        "passed": passed(int(task.task_id)), "semantic_passed": passed(int(task.task_id)),
        "actual_mode": "live", "cost": cost, "replan_count": replans, "policy_catch_count": catches,
    })


def test_council_quality_requires_broad_improvement_without_regression():
    baseline = _evaluation("baseline", passed=lambda index: index < 4, replans=8, catches=1)
    council = _evaluation("council", passed=lambda index: index < 5, replans=0, catches=2)
    result = compare_council_impact(baseline, council, minimum_outcome_improvement=0.1)
    assert result.promote is True
    assert result.replan_delta < 0


def test_council_quality_fails_closed_on_unknown_cost():
    baseline = _evaluation("baseline", passed=lambda _index: False)
    council = run_outcome_evaluation("council", EvaluationSuite("v1", tuple(EvaluationTask(str(i), "bugfix", "do", {}) for i in range(8))),
                                     lambda task: {"passed": True, "semantic_passed": True, "actual_mode": "live"})
    assert compare_council_impact(baseline, council).reason == "cost evidence is unknown"
