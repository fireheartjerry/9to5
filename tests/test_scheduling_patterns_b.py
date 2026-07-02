"""Acceptance tests: recurring task scheduling patterns (st-090) — Part B.

Covers:
  - TestAverageDelayUnderFiveMinutes: average_delay_seconds() stays < MAX_DELAY_SECONDS.
  - TestOverdueDetection: overdue_jobs() surfaces tasks that missed their deadline window.
  - TestCounters: queued/running counts and slot availability tracking.
  - TestCancellation: cancellation removes queued jobs without affecting running ones.

Split from test_scheduling_patterns.py (was 404 lines).
Run: python -m pytest tests/test_scheduling_patterns_b.py
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scheduling.recurring import MAX_DELAY_SECONDS, RecurringScheduler, RecurringTask
from workflows.scheduler import WorkflowJob


class TestAverageDelayUnderFiveMinutes(unittest.TestCase):
    """average_delay_seconds() must remain < MAX_DELAY_SECONDS (300 s)."""

    def test_zero_delay_before_any_completion(self):
        sched = RecurringScheduler()
        self.assertEqual(sched.average_delay_seconds(), 0.0)

    def test_immediate_dispatch_yields_near_zero_delay(self):
        sched = RecurringScheduler(max_concurrent=8)
        t = 4_000_000.0
        sched.register("work", interval_seconds=60, first_due_at=t)
        for tick_offset in [0, 60, 120, 180, 240]:
            sched.tick(now=t + tick_offset)
            j = sched.next()
            if j:
                # Simulate instant start: override to due_at
                due_at = sched._job_due_at[j.job_id]
                sched._job_started_at[j.job_id] = due_at
                sched.complete(j.job_id)
        avg = sched.average_delay_seconds()
        self.assertLess(avg, MAX_DELAY_SECONDS)
        self.assertEqual(avg, 0.0)

    def test_small_delay_accumulates_correctly(self):
        sched = RecurringScheduler(max_concurrent=4)
        t0 = 5_000_000.0
        sched.register("measured", interval_seconds=60, first_due_at=t0)
        sched.tick(now=t0)
        job = sched.next()
        self.assertIsNotNone(job)
        # Simulate 10 s delay: started_at = due_at + 10
        due_at = sched._job_due_at[job.job_id]
        sched._job_started_at[job.job_id] = due_at + 10.0
        sched.complete(job.job_id)
        self.assertAlmostEqual(sched.average_delay_seconds(), 10.0, places=6)

    def test_five_completions_average_under_sla(self):
        sched = RecurringScheduler(max_concurrent=8)
        t0 = 6_000_000.0
        sched.register("periodic", interval_seconds=60, first_due_at=t0)
        for i in range(5):
            sched.tick(now=t0 + i * 60)
            j = sched.next()
            if j:
                due_at = sched._job_due_at[j.job_id]
                # Each job starts 5 s after due time (well under 300 s SLA)
                sched._job_started_at[j.job_id] = due_at + 5.0
                sched.complete(j.job_id)
        self.assertLess(sched.average_delay_seconds(), MAX_DELAY_SECONDS)


class TestOverdueDetection(unittest.TestCase):
    """overdue_jobs() surfaces tasks that missed their deadline window."""

    def test_no_overdue_with_future_deadline(self):
        sched = RecurringScheduler(max_concurrent=4)
        now = time.time()
        # first_due = now-60, max_delay=300 → deadline = now-60+300 = now+240 (future)
        sched.register("fresh", interval_seconds=60, max_delay_seconds=300.0,
                       first_due_at=now - 60)
        sched.tick(now=now)
        self.assertEqual(len(sched.overdue_jobs()), 0)

    def test_job_overdue_when_deadline_passed(self):
        sched = RecurringScheduler(max_concurrent=4)
        now = time.time()
        # first_due = now-100, max_delay=30 → deadline = now-100+30 = now-70 (past)
        sched.register("stale", interval_seconds=60, max_delay_seconds=30.0,
                       first_due_at=now - 100)
        sched.tick(now=now)
        overdue = sched.overdue_jobs()
        self.assertEqual(len(overdue), 1)
        self.assertEqual(overdue[0].workflow_name, "stale")

    def test_running_job_excluded_from_overdue(self):
        sched = RecurringScheduler(max_concurrent=4)
        now = time.time()
        sched.register("running", interval_seconds=60, max_delay_seconds=30.0,
                       first_due_at=now - 100)
        sched.tick(now=now)
        sched.next()  # start the job → it moves to running set
        self.assertEqual(len(sched.overdue_jobs()), 0)

    def test_mixed_fresh_and_stale(self):
        sched = RecurringScheduler(max_concurrent=4)
        now = time.time()
        sched.register("fresh", interval_seconds=60, max_delay_seconds=300.0,
                       first_due_at=now - 60)
        sched.register("stale", interval_seconds=60, max_delay_seconds=30.0,
                       first_due_at=now - 100)
        sched.tick(now=now)
        overdue = sched.overdue_jobs()
        names = [j.workflow_name for j in overdue]
        self.assertIn("stale", names)
        self.assertNotIn("fresh", names)


class TestCounters(unittest.TestCase):
    def setUp(self):
        self.t0 = 7_000_000.0

    def test_queued_count_after_tick(self):
        sched = RecurringScheduler(max_concurrent=4)
        sched.register("a", interval_seconds=60, first_due_at=self.t0)
        sched.register("b", interval_seconds=60, first_due_at=self.t0)
        sched.tick(now=self.t0)
        self.assertEqual(sched.queued_count, 2)

    def test_running_count_after_next(self):
        sched = RecurringScheduler(max_concurrent=4)
        sched.register("a", interval_seconds=60, first_due_at=self.t0)
        sched.tick(now=self.t0)
        j = sched.next()
        self.assertIsNotNone(j)
        self.assertEqual(sched.running_count, 1)
        sched.complete(j.job_id)
        self.assertEqual(sched.running_count, 0)

    def test_queued_count_decrements_on_dispatch(self):
        sched = RecurringScheduler(max_concurrent=4)
        sched.register("a", interval_seconds=60, first_due_at=self.t0)
        sched.register("b", interval_seconds=60, first_due_at=self.t0)
        sched.tick(now=self.t0)
        self.assertEqual(sched.queued_count, 2)
        j = sched.next()
        self.assertEqual(sched.queued_count, 1)
        sched.complete(j.job_id)

    def test_slot_available_property(self):
        sched = RecurringScheduler(max_concurrent=1)
        sched.register("x", interval_seconds=60, first_due_at=self.t0)
        sched.tick(now=self.t0)
        self.assertTrue(sched.slot_available)
        j = sched.next()
        self.assertFalse(sched.slot_available)
        sched.complete(j.job_id)
        self.assertTrue(sched.slot_available)

    def test_empty_scheduler_starts_at_zero(self):
        sched = RecurringScheduler()
        self.assertEqual(sched.queued_count, 0)
        self.assertEqual(sched.running_count, 0)
        self.assertTrue(sched.slot_available)


class TestCancellation(unittest.TestCase):
    def setUp(self):
        self.sched = RecurringScheduler(max_concurrent=4)
        self.t0 = 8_000_000.0

    def test_cancel_removes_queued_job(self):
        self.sched.register("c", interval_seconds=60, first_due_at=self.t0)
        jobs = self.sched.tick(now=self.t0)
        result = self.sched.cancel(jobs[0].job_id)
        self.assertTrue(result)
        self.assertEqual(self.sched.queued_count, 0)

    def test_cancelled_job_skipped_by_next(self):
        self.sched.register("bad", interval_seconds=60, priority=10, first_due_at=self.t0)
        self.sched.register("good", interval_seconds=60, priority=1, first_due_at=self.t0)
        jobs = self.sched.tick(now=self.t0)
        bad_id = next(j.job_id for j in jobs if j.workflow_name == "bad")
        self.sched.cancel(bad_id)
        dispatched = self.sched.next()
        self.assertEqual(dispatched.workflow_name, "good")
        self.sched.complete(dispatched.job_id)
        self.assertIsNone(self.sched.next())

    def test_cancel_running_job_returns_false(self):
        self.sched.register("c", interval_seconds=60, first_due_at=self.t0)
        self.sched.tick(now=self.t0)
        j = self.sched.next()
        self.assertFalse(self.sched.cancel(j.job_id))

    def test_cancel_unknown_returns_false(self):
        self.assertFalse(self.sched.cancel("does-not-exist"))
