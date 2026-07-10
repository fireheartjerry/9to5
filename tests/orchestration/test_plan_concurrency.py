"""Fail-closed plan metadata normalization and opted-in batch selection."""
from platform_core.core.concurrency import boundedWorkerBudget
from platform_core.orchestration.parallel_safety import selectSafeBatch
from platform_core.orchestration.plan_concurrency import normalizePlanConcurrency


def test_normalization_keeps_valid_metadata_and_normalizes_separators():
    plan = normalizePlanConcurrency([
        {"title": "a", "files_touched": ["pkg\\a.py"], "parallel_safe": True},
        {"title": "b", "depends_on": [], "files_touched": ["pkg/b.py"], "parallel_safe": True},
    ])
    assert plan[0]["files_touched"] == ["pkg/a.py"]
    assert all(item["parallel_safe"] for item in plan)


def test_invalid_dependency_serializes_entire_plan():
    plan = normalizePlanConcurrency([
        {"title": "a", "files_touched": ["a.py"], "parallel_safe": True},
        {"title": "b", "depends_on": [2], "files_touched": ["b.py"], "parallel_safe": True},
    ])
    assert [item["parallel_safe"] for item in plan] == [False, False]
    assert [item["depends_on"] for item in plan] == [[], []]


def test_selector_requires_explicit_opt_in_and_disjoint_paths():
    ready = [
        {"subtask_id": "a", "parallel_safe": True, "files_touched": ["a.py"]},
        {"subtask_id": "b", "parallel_safe": True, "files_touched": ["b.py"]},
        {"subtask_id": "c", "parallel_safe": False, "files_touched": ["c.py"]},
    ]
    budget = boundedWorkerBudget(requested=3, configured_cap=3, item_count=3, cpu_count=8)
    assert [item["subtask_id"] for item in selectSafeBatch(ready, budget=budget).selected] == ["a", "b"]
    ready[0]["parallel_safe"] = False
    assert [item["subtask_id"] for item in selectSafeBatch(ready, budget=budget).selected] == ["a"]
