"""Acceptance tests: scheduling optimization patterns (st-065).

Verifies that WorkflowScheduler minimizes delays through:
  - priority-driven dispatch (high-urgency jobs start first)
  - deadline-earliest-first (EDF) tiebreaking
  - immediate slot reuse after completion
  - cancellation short-circuits wasted slots
  - overdue detection enables alerting before execution

Run:
    python C:/9to5/tests/test_scheduling_optimization.py
    python -m pytest tests/test_scheduling_optimization.py
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from workflows.scheduler import WorkflowJob, WorkflowScheduler


class TestPriorityDispatchMinimizesDelay(unittest.TestCase):
    """High-priority jobs are dispatched before lower-priority ones."""

    def setUp(self) -> None:
        self.sched = WorkflowScheduler(max_concurrent=10)

    def test_critical_job_dispatched_before_normal(self) -> None:
        self.sched.enqueue("normal", priority=1)
        self.sched.enqueue("critical", priority=10)
        job = self.sched.next()
        self.assertEqual(job.workflow_name, "critical")
        self.sched.complete(job.job_id)

    def test_dispatch_order_matches_priority_descending(self) -> None:
        for p in [3, 1, 4, 1, 5, 9, 2, 6]:
            self.sched.enqueue(f"wf-{p}", priority=p)
        order = []
        while True:
            job = self.sched.next()
            if job is None:
                break
            order.append(job.priority)
            self.sched.complete(job.job_id)
        for a, b in zip(order, order[1:]):
            self.assertGreaterEqual(a, b, "dispatch order must be non-increasing by priority")

    def test_priority_overrides_arrival_order(self) -> None:
        self.sched.enqueue("arrived_first", priority=1)
        self.sched.enqueue("arrived_second", priority=99)
        job = self.sched.next()
        self.assertEqual(job.workflow_name, "arrived_second")
        self.sched.complete(job.job_id)


class TestEDFTiebreakReducesDeadlineMisses(unittest.TestCase):
    """Equal-priority jobs dispatch in earliest-deadline-first order."""

    def setUp(self) -> None:
        self.sched = WorkflowScheduler(max_concurrent=10)

    def test_earlier_deadline_dispatched_first(self) -> None:
        now = time.time()
        self.sched.enqueue("later", priority=5, deadline=now + 300)
        self.sched.enqueue("sooner", priority=5, deadline=now + 30)
        job = self.sched.next()
        self.assertEqual(job.workflow_name, "sooner")
        self.sched.complete(job.job_id)

    def test_no_deadline_loses_to_deadlined_peer(self) -> None:
        now = time.time()
        self.sched.enqueue("no_dl", priority=3)
        self.sched.enqueue("with_dl", priority=3, deadline=now + 60)
        job = self.sched.next()
        self.assertEqual(job.workflow_name, "with_dl")
        self.sched.complete(job.job_id)

    def test_three_way_edf_ordering(self) -> None:
        now = time.time()
        self.sched.enqueue("c", priority=2, deadline=now + 300)
        self.sched.enqueue("a", priority=2, deadline=now + 10)
        self.sched.enqueue("b", priority=2, deadline=now + 100)
        names = []
        while True:
            job = self.sched.next()
            if job is None:
                break
            names.append(job.workflow_name)
            self.sched.complete(job.job_id)
        self.assertEqual(names, ["a", "b", "c"])


class TestSlotReuseMinimizesQueueDelay(unittest.TestCase):
    """Slots are freed immediately on completion, enabling next dispatch."""

    def test_slot_freed_instantly_on_complete(self) -> None:
        sched = WorkflowScheduler(max_concurrent=1)
        sched.enqueue("first")
        sched.enqueue("second")
        j1 = sched.next()
        self.assertIsNotNone(j1)
        self.assertIsNone(sched.next())   # slot exhausted
        sched.complete(j1.job_id)
        j2 = sched.next()                # slot immediately available
        self.assertIsNotNone(j2)
        sched.complete(j2.job_id)

    def test_multiple_slots_drain_in_priority_order(self) -> None:
        sched = WorkflowScheduler(max_concurrent=2)
        for name, p in [("low", 1), ("high", 9), ("mid", 5)]:
            sched.enqueue(name, priority=p)
        j1 = sched.next()
        j2 = sched.next()
        dispatched = {j1.workflow_name, j2.workflow_name}
        # The two highest-priority jobs must fill the initial slots
        self.assertIn("high", dispatched)
        self.assertIn("mid", dispatched)
        sched.complete(j1.job_id)
        sched.complete(j2.job_id)
        j3 = sched.next()
        self.assertEqual(j3.workflow_name, "low")
        sched.complete(j3.job_id)

    def test_running_and_queued_counts_stay_consistent(self) -> None:
        sched = WorkflowScheduler(max_concurrent=3)
        for i in range(5):
            sched.enqueue(f"wf-{i}", priority=i)
        self.assertEqual(sched.queued_count, 5)
        jobs = []
        for _ in range(3):
            j = sched.next()
            self.assertIsNotNone(j)
            jobs.append(j)
        self.assertEqual(sched.running_count, 3)
        self.assertEqual(sched.queued_count, 2)
        sched.complete(jobs[0].job_id)
        self.assertEqual(sched.running_count, 2)
        self.assertEqual(sched.queued_count, 2)


class TestCancellationAvoidsWastedSlots(unittest.TestCase):
    """Cancelling stale jobs keeps queue lean and avoids slot waste."""

    def setUp(self) -> None:
        self.sched = WorkflowScheduler(max_concurrent=4)

    def test_cancelled_job_does_not_occupy_slot(self) -> None:
        bad = self.sched.enqueue("stale")
        good = self.sched.enqueue("live")
        self.sched.cancel(bad.job_id)
        job = self.sched.next()
        self.assertEqual(job.workflow_name, "live")
        self.assertEqual(self.sched.queued_count, 0)
        self.sched.complete(job.job_id)

    def test_cancel_running_job_not_allowed(self) -> None:
        job = self.sched.enqueue("running")
        self.sched.next()
        result = self.sched.cancel(job.job_id)
        self.assertFalse(result)

    def test_cancel_unknown_job_returns_false(self) -> None:
        self.assertFalse(self.sched.cancel("ghost-id"))

    def test_bulk_cancel_leaves_queue_clean(self) -> None:
        jobs = [self.sched.enqueue(f"j{i}") for i in range(5)]
        for j in jobs[:4]:
            self.sched.cancel(j.job_id)
        self.assertEqual(self.sched.queued_count, 1)
        remaining = self.sched.next()
        self.assertEqual(remaining.workflow_name, "j4")
        self.sched.complete(remaining.job_id)


class TestOverdueDetectionEnablesEarlyAlert(unittest.TestCase):
    """overdueJobs() surfaces missed-deadline tasks before they start."""

    def setUp(self) -> None:
        self.sched = WorkflowScheduler(max_concurrent=4)

    def test_future_deadline_not_overdue(self) -> None:
        self.sched.enqueue("ok", deadline=time.time() + 999)
        self.assertEqual(self.sched.overdueJobs(), [])

    def test_past_deadline_detected(self) -> None:
        self.sched.enqueue("expired", deadline=time.time() - 1)
        overdue = self.sched.overdueJobs()
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0].workflow_name, "expired")

    def test_running_job_excluded_from_overdue(self) -> None:
        self.sched.enqueue("running", deadline=time.time() - 1)
        self.sched.next()
        self.assertEqual(self.sched.overdueJobs(), [])

    def test_no_deadline_never_overdue(self) -> None:
        self.sched.enqueue("nodl")
        self.assertEqual(self.sched.overdueJobs(), [])

    def test_mixed_overdue_and_fresh(self) -> None:
        self.sched.enqueue("stale", deadline=time.time() - 5)
        self.sched.enqueue("fresh", deadline=time.time() + 500)
        overdue = self.sched.overdueJobs()
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0].workflow_name, "stale")


class TestStartedAtTimestamp(unittest.TestCase):
    """started_at is recorded the moment a job is dispatched."""

    def test_started_at_set_on_dispatch(self) -> None:
        sched = WorkflowScheduler()
        sched.enqueue("wf")
        before = time.time()
        job = sched.next()
        after = time.time()
        self.assertIsNotNone(job.started_at)
        self.assertGreaterEqual(job.started_at, before)
        self.assertLessEqual(job.started_at, after)
        sched.complete(job.job_id)

    def test_started_at_none_before_dispatch(self) -> None:
        job = WorkflowScheduler().enqueue("wf")
        self.assertIsNone(job.started_at)
