"""Tests for workflows.scheduler -- WorkflowScheduler priority/deadline/slot logic.

Acceptance criteria verified:
  * higher priority jobs are dequeued first
  * equal-priority jobs break ties by earliest deadline (EDF)
  * slot cap: next() returns None when max_concurrent reached
  * complete() frees a slot so next() can proceed
  * cancel() removes a queued job; subsequent next() skips it
  * overdueJobs() returns queued jobs whose deadline has passed
  * queued_count and running_count reflect correct state
  * slot_available reflects slot cap

Run: python -m pytest tests/test_scheduling.py
     python C:\\9to5\\tests\\test_scheduling.py
"""
import sys
import time
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from workflows.scheduler import WorkflowScheduler, WorkflowJob


class TestEnqueue(unittest.TestCase):
    def setUp(self):
        self.sched = WorkflowScheduler(max_concurrent=4)

    def test_enqueue_returns_job(self):
        job = self.sched.enqueue("wf1")
        self.assertIsInstance(job, WorkflowJob)
        self.assertEqual(job.workflow_name, "wf1")

    def test_custom_job_id_respected(self):
        job = self.sched.enqueue("wf1", job_id="custom-1")
        self.assertEqual(job.job_id, "custom-1")

    def test_queued_count_increments(self):
        self.sched.enqueue("wf1")
        self.sched.enqueue("wf2")
        self.assertEqual(self.sched.queued_count, 2)

    def test_invalid_max_concurrent_raises(self):
        with self.assertRaises(ValueError):
            WorkflowScheduler(max_concurrent=0)


class TestPriorityOrdering(unittest.TestCase):
    def setUp(self):
        self.sched = WorkflowScheduler(max_concurrent=10)

    def test_higher_priority_dequeued_first(self):
        self.sched.enqueue("low", priority=1)
        self.sched.enqueue("high", priority=5)
        self.sched.enqueue("mid", priority=3)
        names = []
        while True:
            job = self.sched.next()
            if job is None:
                break
            names.append(job.workflow_name)
            self.sched.complete(job.job_id)
        self.assertEqual(names, ["high", "mid", "low"])

    def test_edf_tiebreak_on_equal_priority(self):
        now = time.time()
        self.sched.enqueue("late", priority=1, deadline=now + 200)
        self.sched.enqueue("early", priority=1, deadline=now + 50)
        first = self.sched.next()
        self.assertEqual(first.workflow_name, "early")
        self.sched.complete(first.job_id)
        second = self.sched.next()
        self.assertEqual(second.workflow_name, "late")
        self.sched.complete(second.job_id)

    def test_no_deadline_runs_after_deadlined(self):
        now = time.time()
        self.sched.enqueue("nodl", priority=1)
        self.sched.enqueue("dl", priority=1, deadline=now + 10)
        first = self.sched.next()
        self.assertEqual(first.workflow_name, "dl")
        self.sched.complete(first.job_id)


class TestSlotCap(unittest.TestCase):
    def test_slot_cap_blocks_next(self):
        sched = WorkflowScheduler(max_concurrent=2)
        sched.enqueue("wf1")
        sched.enqueue("wf2")
        sched.enqueue("wf3")
        j1 = sched.next()
        j2 = sched.next()
        self.assertIsNotNone(j1)
        self.assertIsNotNone(j2)
        # slots exhausted
        self.assertIsNone(sched.next())

    def test_complete_frees_slot(self):
        sched = WorkflowScheduler(max_concurrent=1)
        sched.enqueue("wf1")
        sched.enqueue("wf2")
        j1 = sched.next()
        self.assertIsNotNone(j1)
        self.assertIsNone(sched.next())
        sched.complete(j1.job_id)
        j2 = sched.next()
        self.assertIsNotNone(j2)

    def test_slot_available_property(self):
        sched = WorkflowScheduler(max_concurrent=1)
        self.assertTrue(sched.slot_available)
        sched.enqueue("wf1")
        j = sched.next()
        self.assertFalse(sched.slot_available)
        sched.complete(j.job_id)
        self.assertTrue(sched.slot_available)

    def test_running_count(self):
        sched = WorkflowScheduler(max_concurrent=3)
        sched.enqueue("a")
        sched.enqueue("b")
        j1 = sched.next()
        self.assertEqual(sched.running_count, 1)
        j2 = sched.next()
        self.assertEqual(sched.running_count, 2)
        sched.complete(j1.job_id)
        self.assertEqual(sched.running_count, 1)


class TestCancel(unittest.TestCase):
    def setUp(self):
        self.sched = WorkflowScheduler(max_concurrent=4)

    def test_cancel_queued_job(self):
        job = self.sched.enqueue("wf1")
        result = self.sched.cancel(job.job_id)
        self.assertTrue(result)
        self.assertEqual(self.sched.queued_count, 0)

    def test_cancel_skipped_by_next(self):
        job = self.sched.enqueue("cancelled")
        self.sched.enqueue("remaining")
        self.sched.cancel(job.job_id)
        popped = self.sched.next()
        self.assertEqual(popped.workflow_name, "remaining")
        self.sched.complete(popped.job_id)
        self.assertIsNone(self.sched.next())

    def test_cancel_running_returns_false(self):
        job = self.sched.enqueue("wf1")
        self.sched.next()
        self.assertFalse(self.sched.cancel(job.job_id))

    def test_cancel_unknown_returns_false(self):
        self.assertFalse(self.sched.cancel("nonexistent"))


class TestOverdueJobs(unittest.TestCase):
    def setUp(self):
        self.sched = WorkflowScheduler(max_concurrent=4)

    def test_no_overdue_with_future_deadlines(self):
        self.sched.enqueue("wf1", deadline=time.time() + 999)
        self.assertEqual(self.sched.overdueJobs(), [])

    def test_past_deadline_is_overdue(self):
        self.sched.enqueue("wf1", deadline=time.time() - 1)
        overdue = self.sched.overdueJobs()
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0].workflow_name, "wf1")

    def test_running_jobs_excluded_from_overdue(self):
        job = self.sched.enqueue("wf1", deadline=time.time() - 1)
        self.sched.next()  # start it
        self.assertEqual(self.sched.overdueJobs(), [])

    def test_no_deadline_never_overdue(self):
        self.sched.enqueue("wf1")
        self.assertEqual(self.sched.overdueJobs(), [])


class TestIsOverdue(unittest.TestCase):
    def test_future_deadline_not_overdue(self):
        job = WorkflowJob("j1", "wf", 0, time.time() + 999)
        self.assertFalse(job.isOverdue())

    def test_past_deadline_overdue(self):
        job = WorkflowJob("j1", "wf", 0, time.time() - 1)
        self.assertTrue(job.isOverdue())

    def test_no_deadline_not_overdue(self):
        job = WorkflowJob("j1", "wf", 0, float("inf"))
        self.assertFalse(job.isOverdue())


class TestEmptyQueue(unittest.TestCase):
    def test_next_on_empty_returns_none(self):
        sched = WorkflowScheduler()
        self.assertIsNone(sched.next())

    def test_queued_and_running_start_at_zero(self):
        sched = WorkflowScheduler()
        self.assertEqual(sched.queued_count, 0)
        self.assertEqual(sched.running_count, 0)
