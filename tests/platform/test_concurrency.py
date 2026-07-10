"""Contracts for the bounded blocking-work scheduler."""
from __future__ import annotations

import contextvars
import threading

from platform_core.core.concurrency import boundedWorkerBudget, runBounded


def test_budget_conservatively_clamps_every_input():
    budget = boundedWorkerBudget(requested=99, configured_cap=3, item_count=9, cpu_count=2)
    assert budget.effective == 2
    assert budget.limited_by == ("cpu",)


def test_budget_handles_missing_or_small_inputs():
    assert boundedWorkerBudget(requested=0, configured_cap=0, item_count=0, cpu_count=None).effective == 0
    assert boundedWorkerBudget(requested=9, configured_cap=9, item_count=1, cpu_count=1).effective == 1


def test_run_bounded_preserves_order_context_and_failures():
    marker = contextvars.ContextVar("marker", default="missing")
    marker.set("run-42")
    started = threading.Event()

    def worker(value: int) -> tuple[int, str]:
        started.set()
        if value == 2:
            raise ValueError("boom")
        return value, marker.get()

    budget = boundedWorkerBudget(requested=3, configured_cap=3, item_count=3, cpu_count=8)
    outcomes = runBounded([1, 2, 3], worker, budget=budget)
    assert started.is_set()
    assert outcomes[0].value == (1, "run-42")
    assert isinstance(outcomes[1].error, ValueError)
    assert outcomes[2].value == (3, "run-42")
