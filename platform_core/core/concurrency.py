"""Bounded, context-aware helpers for blocking concurrent work.

These helpers deliberately own scheduling only.  Callers retain domain state and
must decide how results or failures affect their transaction/state machine.
"""
from __future__ import annotations

import contextvars
import math
import os
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from typing import Callable, Generic, Literal, Sequence, TypeVar

T = TypeVar("T")
R = TypeVar("R")
LimitReason = Literal["request", "cap", "cpu", "items"]


@dataclass(frozen=True, slots=True)
class WorkerBudget:
    requested: int
    configured_cap: int
    cpu_count: int
    item_count: int
    effective: int
    limited_by: tuple[LimitReason, ...]


@dataclass(frozen=True, slots=True)
class WorkerFailure:
    subtask_id: str
    phase: Literal["provision", "attempt", "merge", "cleanup"]
    error_type: str
    message: str


@dataclass(frozen=True, slots=True)
class BoundedResult(Generic[R]):
    value: R | None
    error: BaseException | None


def boundedWorkerBudget(
    *, requested: int, configured_cap: int, item_count: int, cpu_count: int | None = None
) -> WorkerBudget:
    """Return a conservative worker budget without trusting host or caller inputs."""
    cpu = max(1, int(cpu_count if cpu_count is not None else (os.cpu_count() or 1)))
    req = max(1, int(requested))
    cap = max(1, int(configured_cap))
    items = max(0, int(item_count))
    auto = min(4, max(2, math.ceil(cpu / 2)))
    candidates: dict[LimitReason, int] = {"request": req, "cap": cap, "cpu": auto, "items": items}
    effective = min(candidates.values(), default=0)
    limited_by = tuple(name for name, value in candidates.items() if value == effective)
    return WorkerBudget(req, cap, cpu, items, effective, limited_by)


def runBounded(
    items: Sequence[T], worker: Callable[[T], R], *, budget: WorkerBudget,
    context: contextvars.Context | None = None,
) -> list[BoundedResult[R]]:
    """Run blocking work with bounded fan-out and return outcomes in input order.

    Every started future is joined before return.  A copied context is made per
    future because one ``Context`` object cannot enter multiple threads at once.
    """
    if not items:
        return []
    workers = max(1, min(len(items), budget.effective))
    parent = context or contextvars.copy_context()
    results: list[BoundedResult[R] | None] = [None] * len(items)

    def invoke(item: T) -> R:
        return parent.copy().run(worker, item)

    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="9to5-bounded") as pool:
        futures: dict[Future[R], int] = {pool.submit(invoke, item): index for index, item in enumerate(items)}
        for future in as_completed(futures):
            index = futures[future]
            try:
                results[index] = BoundedResult(value=future.result(), error=None)
            except BaseException as exc:  # callers decide whether aggregated failures are fatal
                results[index] = BoundedResult(value=None, error=exc)
    return [result for result in results if result is not None]
