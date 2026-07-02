"""Acceptance tests for the priority-queue scheduler (st-057).

Verifies that WorkflowScheduler allocates slots based on task urgency and deadlines.

Run: python C:/9to5/tests/test_priority_scheduler.py
     python -m pytest tests/test_priority_scheduler.py
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


class TestPriorityQueueBasics(unittest.TestCase):
    """Priority ordering — higher urgency number wins."""

    def setUp(self) -> None:
        self.sched = WorkflowScheduler(max_concurrent=10)

    def test_highest_priority_dequeued_first(self) -> None:
        self.sched.enqueue("critical", priority=10)
        self.sched.enqueue("normal", priority=5)
        self.sched.enqueue("low", priority=1)
        order = []
        while True:
            job = self.sched.next()
            if job is None:
                break
            order.append(job.workflow_name)
            self.sched.complete(job.job_id)
        self.assertEqual(order, ["critical", "normal", "low"])

    def test_equal_priority_edf_tiebreak(self) -> None:
        now = time.time()
        self.sched.enqueue("urgent", priority=3, deadline=now + 30)
        self.sched.enqueue("later", priority=3, deadline=now + 300)
        first = self.sched.next()
        self.assertEqual(first.workflow_name, "urgent")
        self.sched.complete(first.job_id)
        second = self.sched.next()
        self.assertEqual(second.workflow_name, "later")
        self.sched.complete(second.job_id)

    def test_no_deadline_loses_to_deadlined_peer(self) -> None:
        now = time.time()
        self.sched.enqueue("no_dl", priority=2)
        self.sched.enqueue("with_dl", priority=2, deadline=now + 60)
        first = self.sched.next()
        self.assertEqual(first.workflow_name, "with_dl")
        self.sched.complete(first.job_id)

    def test_priority_overrides_earlier_enqueue(self) -> None:
        self.sched.enqueue("first_in", priority=1)
        self.sched.enqueue("second_in", priority=99)
        job = self.sched.next()
        self.assertEqual(job.workflow_name, "second_in")
        self.sched.complete(job.job_id)


class TestDeadlineAwareAllocation(unittest.TestCase):
    """Deadline fields are preserved on the job object."""

    def test_deadline_stored_on_job(self) -> None:
        dl = time.time() + 120
        job = WorkflowScheduler().enqueue("wf", deadline=dl)
        self.assertAlmostEqual(job.deadline, dl, places=3)

    def test_no_deadline_stored_as_inf(self) -> None:
        job = WorkflowScheduler().enqueue("wf")
        self.assertEqual(job.deadline, float("inf"))

    def test_overdue_detection(self) -> None:
        sched = WorkflowScheduler(max_concurrent=4)
        sched.enqueue("expired", deadline=time.time() - 5)
        sched.enqueue("fresh", deadline=time.time() + 999)
        overdue = sched.overdueJobs()
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0].workflow_name, "expired")

    def test_overdue_job_is_overdue(self) -> None:
        job = WorkflowJob("j", "wf", 0, time.time() - 1)
        self.assertTrue(job.isOverdue())

    def test_future_deadline_not_overdue(self) -> None:
        job = WorkflowJob("j", "wf", 0, time.time() + 999)
        self.assertFalse(job.isOverdue())


class TestSlotAllocation(unittest.TestCase):
    """Slot cap enforces max_concurrent limit."""

    def test_slot_cap_blocks_when_full(self) -> None:
        sched = WorkflowScheduler(max_concurrent=2)
        sched.enqueue("a", priority=1)
        sched.enqueue("b", priority=2)
        sched.enqueue("c", priority=3)
        j1 = sched.next()
        j2 = sched.next()
        self.assertIsNotNone(j1)
        self.assertIsNotNone(j2)
        self.assertIsNone(sched.next())  # slots exhausted

    def test_complete_releases_slot(self) -> None:
        sched = WorkflowScheduler(max_concurrent=1)
        sched.enqueue("first")
        sched.enqueue("second")
        j = sched.next()
        self.assertIsNone(sched.next())
        sched.complete(j.job_id)
        nxt = sched.next()
        self.assertIsNotNone(nxt)

    def test_running_count_tracks_active_jobs(self) -> None:
        sched = WorkflowScheduler(max_concurrent=5)
        sched.enqueue("x")
        sched.enqueue("y")
        j1 = sched.next()
        self.assertEqual(sched.running_count, 1)
        sched.next()
        self.assertEqual(sched.running_count, 2)
        sched.complete(j1.job_id)
        self.assertEqual(sched.running_count, 1)

    def test_queued_count_decrements_on_next(self) -> None:
        sched = WorkflowScheduler(max_concurrent=5)
        sched.enqueue("a")
        sched.enqueue("b")
        self.assertEqual(sched.queued_count, 2)
        j = sched.next()
        self.assertEqual(sched.queued_count, 1)
        sched.complete(j.job_id)
        self.assertEqual(sched.queued_count, 1)

    def test_slot_available_property(self) -> None:
        sched = WorkflowScheduler(max_concurrent=1)
        self.assertTrue(sched.slot_available)
        sched.enqueue("wf")
        j = sched.next()
        self.assertFalse(sched.slot_available)
        sched.complete(j.job_id)
        self.assertTrue(sched.slot_available)


class TestCancellation(unittest.TestCase):
    """cancel() removes a queued job without affecting running jobs."""

    def setUp(self) -> None:
        self.sched = WorkflowScheduler(max_concurrent=4)

    def test_cancel_removes_queued_job(self) -> None:
        job = self.sched.enqueue("to_cancel")
        self.assertTrue(self.sched.cancel(job.job_id))
        self.assertEqual(self.sched.queued_count, 0)

    def test_cancelled_job_skipped_by_next(self) -> None:
        bad = self.sched.enqueue("gone")
        self.sched.enqueue("keep")
        self.sched.cancel(bad.job_id)
        popped = self.sched.next()
        self.assertEqual(popped.workflow_name, "keep")
        self.sched.complete(popped.job_id)
        self.assertIsNone(self.sched.next())

    def test_cancel_running_returns_false(self) -> None:
        job = self.sched.enqueue("wf")
        self.sched.next()
        self.assertFalse(self.sched.cancel(job.job_id))

    def test_cancel_unknown_returns_false(self) -> None:
        self.assertFalse(self.sched.cancel("does-not-exist"))

    def test_cancel_releases_dependents(self) -> None:
        # B34: A blocks B; cancelling A must release B (never leave it waiting on
        # a dependency that can never complete).
        a = self.sched.enqueue("A")
        self.sched.enqueue("B", depends_on=[a.job_id])
        self.assertTrue(self.sched.cancel(a.job_id))
        self.assertEqual(self.sched.queued_count, 0)  # B released, not stuck
        self.assertIsNone(self.sched.next())          # nothing runnable remains

    def test_cancel_releases_dependents_transitively(self) -> None:
        a = self.sched.enqueue("A")
        b = self.sched.enqueue("B", depends_on=[a.job_id])
        self.sched.enqueue("C", depends_on=[b.job_id])
        self.sched.cancel(a.job_id)
        self.assertEqual(self.sched.queued_count, 0)  # B and C released too


class TestCompleteHygiene(unittest.TestCase):
    """complete() ignores unknown ids (B35)."""

    def test_complete_unknown_id_is_noop(self) -> None:
        sched = WorkflowScheduler(max_concurrent=2)
        sched.complete("never-enqueued")
        self.assertEqual(len(sched._completed), 0)  # unknown id not recorded

    def test_complete_known_id_is_recorded(self) -> None:
        sched = WorkflowScheduler(max_concurrent=2)
        sched.enqueue("wf", job_id="known")
        job = sched.next()
        sched.complete(job.job_id)
        self.assertIn("known", sched._completed)


class TestEdgeCases(unittest.TestCase):
    def test_empty_queue_returns_none(self) -> None:
        sched = WorkflowScheduler()
        self.assertIsNone(sched.next())

    def test_invalid_max_concurrent_raises(self) -> None:
        with self.assertRaises(ValueError):
            WorkflowScheduler(max_concurrent=0)

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

    def test_mixed_priority_many_jobs(self) -> None:
        sched = WorkflowScheduler(max_concurrent=20)
        priorities = [3, 1, 4, 1, 5, 9, 2, 6, 5, 3]
        for i, p in enumerate(priorities):
            sched.enqueue(f"wf_{i}", priority=p)
        order = []
        while True:
            job = sched.next()
            if job is None:
                break
            order.append(job.priority)
            sched.complete(job.job_id)
        # must be non-increasing
        for a, b in zip(order, order[1:]):
            self.assertGreaterEqual(a, b)


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2)
    sys.exit(0 if result.result.wasSuccessful() else 1)
