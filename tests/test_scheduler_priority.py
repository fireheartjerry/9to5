"""Acceptance tests for priority-queue scheduler with dependency support (st-068).

Verifies task allocation based on urgency (priority/deadline) and dependencies.

Run: python C:/9to5/tests/test_scheduler_priority.py
     python -m pytest tests/test_scheduler_priority.py
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


class TestPriorityOrdering(unittest.TestCase):
    """Priority ordering — higher urgency value wins."""

    def setUp(self) -> None:
        self.sched = WorkflowScheduler(max_concurrent=10)

    def test_highest_priority_first(self) -> None:
        self.sched.enqueue("low", priority=1)
        self.sched.enqueue("high", priority=10)
        self.sched.enqueue("mid", priority=5)
        order = []
        while True:
            job = self.sched.next()
            if job is None:
                break
            order.append(job.workflow_name)
            self.sched.complete(job.job_id)
        self.assertEqual(order, ["high", "mid", "low"])

    def test_edf_tiebreak_on_equal_priority(self) -> None:
        now = time.time()
        self.sched.enqueue("sooner", priority=3, deadline=now + 30)
        self.sched.enqueue("later", priority=3, deadline=now + 300)
        first = self.sched.next()
        self.assertEqual(first.workflow_name, "sooner")
        self.sched.complete(first.job_id)
        second = self.sched.next()
        self.assertEqual(second.workflow_name, "later")

    def test_priority_beats_fifo(self) -> None:
        self.sched.enqueue("first_in", priority=1)
        self.sched.enqueue("second_in", priority=99)
        job = self.sched.next()
        self.assertEqual(job.workflow_name, "second_in")

    def test_nonincreasing_priority_stream(self) -> None:
        sched = WorkflowScheduler(max_concurrent=20)
        for i, p in enumerate([3, 1, 4, 1, 5, 9, 2, 6]):
            sched.enqueue(f"wf_{i}", priority=p)
        order = []
        while True:
            job = sched.next()
            if job is None:
                break
            order.append(job.priority)
            sched.complete(job.job_id)
        for a, b in zip(order, order[1:]):
            self.assertGreaterEqual(a, b)


class TestDependencies(unittest.TestCase):
    """Dependency-based deferral — a job waits for its depends_on to complete."""

    def setUp(self) -> None:
        self.sched = WorkflowScheduler(max_concurrent=10)

    def test_dependent_job_deferred_until_dep_completes(self) -> None:
        a = self.sched.enqueue("setup", priority=5)
        self.sched.enqueue("build", priority=5, depends_on=[a.job_id])
        # Only "setup" should be runnable now
        first = self.sched.next()
        self.assertIsNotNone(first)
        self.assertEqual(first.workflow_name, "setup")
        # "build" still blocked
        self.assertIsNone(self.sched.next())
        # complete setup → build unblocks
        self.sched.complete(first.job_id)
        second = self.sched.next()
        self.assertIsNotNone(second)
        self.assertEqual(second.workflow_name, "build")

    def test_higher_priority_dep_free_runs_before_lower_dep_blocked(self) -> None:
        a = self.sched.enqueue("gate", priority=1)
        self.sched.enqueue("blocked_high", priority=10, depends_on=[a.job_id])
        self.sched.enqueue("free_low", priority=2)
        # blocked_high (p=10) has unmet dep, so it is skipped; free_low (p=2) runs
        # before gate (p=1) because blocked_high no longer holds the top spot.
        first = self.sched.next()
        self.assertEqual(first.workflow_name, "free_low")
        self.sched.complete(first.job_id)
        # gate (p=1) runs next; blocked_high still blocked
        second = self.sched.next()
        self.assertEqual(second.workflow_name, "gate")
        self.sched.complete(second.job_id)
        # Now blocked_high's dep is satisfied
        third = self.sched.next()
        self.assertEqual(third.workflow_name, "blocked_high")

    def test_chain_of_three_deps(self) -> None:
        a = self.sched.enqueue("step1", priority=1)
        b = self.sched.enqueue("step2", priority=1, depends_on=[a.job_id])
        self.sched.enqueue("step3", priority=1, depends_on=[b.job_id])

        j1 = self.sched.next()
        self.assertEqual(j1.workflow_name, "step1")
        self.assertIsNone(self.sched.next())  # step2 and step3 both blocked
        self.sched.complete(j1.job_id)

        j2 = self.sched.next()
        self.assertEqual(j2.workflow_name, "step2")
        self.assertIsNone(self.sched.next())  # step3 still blocked
        self.sched.complete(j2.job_id)

        j3 = self.sched.next()
        self.assertEqual(j3.workflow_name, "step3")
        self.sched.complete(j3.job_id)

    def test_depends_on_stored_on_job(self) -> None:
        a = self.sched.enqueue("a")
        b = self.sched.enqueue("b", depends_on=[a.job_id])
        self.assertEqual(b.depends_on, [a.job_id])

    def test_no_depends_on_defaults_empty(self) -> None:
        job = self.sched.enqueue("wf")
        self.assertEqual(job.depends_on, [])

    def test_already_completed_dep_allows_immediate_run(self) -> None:
        a = self.sched.enqueue("prereq")
        j = self.sched.next()
        self.sched.complete(j.job_id)
        b = self.sched.enqueue("follower", depends_on=[a.job_id])
        result = self.sched.next()
        self.assertIsNotNone(result)
        self.assertEqual(result.workflow_name, "follower")


class TestSlotManagement(unittest.TestCase):
    def test_slot_cap_enforced(self) -> None:
        sched = WorkflowScheduler(max_concurrent=2)
        for name in ["a", "b", "c"]:
            sched.enqueue(name)
        j1 = sched.next()
        j2 = sched.next()
        self.assertIsNotNone(j1)
        self.assertIsNotNone(j2)
        self.assertIsNone(sched.next())

    def test_complete_releases_slot(self) -> None:
        sched = WorkflowScheduler(max_concurrent=1)
        sched.enqueue("first")
        sched.enqueue("second")
        j = sched.next()
        self.assertIsNone(sched.next())
        sched.complete(j.job_id)
        self.assertIsNotNone(sched.next())

    def test_running_count_tracks_active(self) -> None:
        sched = WorkflowScheduler(max_concurrent=5)
        sched.enqueue("x")
        sched.enqueue("y")
        j1 = sched.next()
        self.assertEqual(sched.running_count, 1)
        j2 = sched.next()
        self.assertEqual(sched.running_count, 2)
        sched.complete(j1.job_id)
        self.assertEqual(sched.running_count, 1)


class TestCancellation(unittest.TestCase):
    def test_cancel_removes_queued_job(self) -> None:
        sched = WorkflowScheduler(max_concurrent=4)
        job = sched.enqueue("to_cancel")
        self.assertTrue(sched.cancel(job.job_id))
        self.assertEqual(sched.queued_count, 0)

    def test_cancelled_job_skipped_by_next(self) -> None:
        sched = WorkflowScheduler(max_concurrent=4)
        bad = sched.enqueue("gone")
        good = sched.enqueue("keep")
        sched.cancel(bad.job_id)
        popped = sched.next()
        self.assertEqual(popped.workflow_name, "keep")
        sched.complete(popped.job_id)
        self.assertIsNone(sched.next())

    def test_cancel_running_returns_false(self) -> None:
        sched = WorkflowScheduler(max_concurrent=4)
        job = sched.enqueue("wf")
        sched.next()
        self.assertFalse(sched.cancel(job.job_id))


class TestEdgeCases(unittest.TestCase):
    def test_empty_queue_returns_none(self) -> None:
        self.assertIsNone(WorkflowScheduler().next())

    def test_invalid_max_concurrent_raises(self) -> None:
        with self.assertRaises(ValueError):
            WorkflowScheduler(max_concurrent=0)

    def test_overdue_detection(self) -> None:
        sched = WorkflowScheduler(max_concurrent=4)
        sched.enqueue("expired", deadline=time.time() - 5)
        sched.enqueue("fresh", deadline=time.time() + 999)
        overdue = sched.overdueJobs()
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0].workflow_name, "expired")

    def test_custom_job_id_preserved(self) -> None:
        job = WorkflowScheduler().enqueue("wf", job_id="my-id")
        self.assertEqual(job.job_id, "my-id")

    def test_started_at_set_on_next(self) -> None:
        sched = WorkflowScheduler()
        sched.enqueue("wf")
        before = time.time()
        job = sched.next()
        after = time.time()
        self.assertIsNotNone(job.started_at)
        self.assertGreaterEqual(job.started_at, before)
        self.assertLessEqual(job.started_at, after)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2)
    sys.exit(0 if result.result.wasSuccessful() else 1)
