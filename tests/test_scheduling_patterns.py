"""Acceptance tests: recurring task scheduling patterns (st-090).

Verifies that RecurringScheduler:
  - enqueues tasks when their interval expires
  - does NOT double-enqueue within the same interval
  - dispatches higher-priority tasks first (priority queue)
  - assigns deadlines = due_time + max_delay_seconds (deadline-aware allocation)
  - keeps average start delay < 5 minutes (300 s) under normal conditions
  - surfaces overdue jobs via overdue_jobs()
  - correctly tracks queued/running counts and slot availability
  - cancellation removes queued jobs without affecting running ones

Run:
    python C:\\9to5\\tests\\test_scheduling_patterns.py
    python -m pytest tests/test_scheduling_patterns.py
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


class TestRegister(unittest.TestCase):
    def test_register_returns_recurring_task(self):
        sched = RecurringScheduler()
        task = sched.register("ping", interval_seconds=60)
        self.assertIsInstance(task, RecurringTask)
        self.assertEqual(task.task_id, "ping")
        self.assertEqual(task.interval_seconds, 60)

    def test_default_max_delay_is_five_minutes(self):
        sched = RecurringScheduler()
        task = sched.register("t", interval_seconds=30)
        self.assertEqual(task.max_delay_seconds, MAX_DELAY_SECONDS)
        self.assertEqual(MAX_DELAY_SECONDS, 300.0)

    def test_invalid_interval_zero_raises(self):
        with self.assertRaises(ValueError):
            RecurringScheduler().register("bad", interval_seconds=0)

    def test_invalid_interval_negative_raises(self):
        with self.assertRaises(ValueError):
            RecurringScheduler().register("bad", interval_seconds=-5)

    def test_custom_priority_stored(self):
        task = RecurringScheduler().register("t", interval_seconds=60, priority=7)
        self.assertEqual(task.priority, 7)

    def test_custom_max_delay_stored(self):
        task = RecurringScheduler().register("t", interval_seconds=60, max_delay_seconds=120.0)
        self.assertEqual(task.max_delay_seconds, 120.0)


class TestTickEnqueue(unittest.TestCase):
    """tick() enqueues tasks exactly when their interval has elapsed."""

    def setUp(self):
        self.sched = RecurringScheduler(max_concurrent=8)
        self.t0 = 1_000_000.0  # fixed base; far enough in past for deadline tests

    def test_tick_at_due_time_enqueues_job(self):
        self.sched.register("health", interval_seconds=60, first_due_at=self.t0)
        jobs = self.sched.tick(now=self.t0)
        self.assertEqual(len(jobs), 1)
        self.assertIsInstance(jobs[0], WorkflowJob)
        self.assertEqual(jobs[0].workflow_name, "health")

    def test_tick_before_due_time_enqueues_nothing(self):
        self.sched.register("health", interval_seconds=60, first_due_at=self.t0 + 30)
        jobs = self.sched.tick(now=self.t0)
        self.assertEqual(len(jobs), 0)

    def test_no_double_enqueue_within_same_interval(self):
        self.sched.register("check", interval_seconds=60, first_due_at=self.t0)
        self.sched.tick(now=self.t0)
        jobs = self.sched.tick(now=self.t0 + 10)
        self.assertEqual(len(jobs), 0)

    def test_second_interval_enqueues_after_first(self):
        self.sched.register("check", interval_seconds=60, first_due_at=self.t0)
        jobs1 = self.sched.tick(now=self.t0)
        self.assertEqual(len(jobs1), 1)
        j = self.sched.next()
        self.sched.complete(j.job_id)
        jobs2 = self.sched.tick(now=self.t0 + 60)
        self.assertEqual(len(jobs2), 1)

    def test_multiple_tasks_all_enqueued_on_tick(self):
        for i in range(3):
            self.sched.register(f"task-{i}", interval_seconds=60, first_due_at=self.t0)
        jobs = self.sched.tick(now=self.t0)
        self.assertEqual(len(jobs), 3)

    def test_job_workflow_name_matches_task_id(self):
        self.sched.register("my-task", interval_seconds=60, first_due_at=self.t0)
        jobs = self.sched.tick(now=self.t0)
        self.assertEqual(jobs[0].workflow_name, "my-task")


class TestPriorityOrdering(unittest.TestCase):
    """Priority queue dispatches higher-urgency tasks first."""

    def setUp(self):
        self.sched = RecurringScheduler(max_concurrent=10)
        self.t0 = 2_000_000.0

    def test_high_priority_dispatched_first(self):
        self.sched.register("low", interval_seconds=60, priority=1, first_due_at=self.t0)
        self.sched.register("high", interval_seconds=60, priority=10, first_due_at=self.t0)
        self.sched.tick(now=self.t0)
        job = self.sched.next()
        self.assertEqual(job.workflow_name, "high")
        self.sched.complete(job.job_id)

    def test_dispatch_order_is_priority_descending(self):
        for name, p in [("critical", 10), ("normal", 5), ("background", 1)]:
            self.sched.register(name, interval_seconds=60, priority=p, first_due_at=self.t0)
        self.sched.tick(now=self.t0)
        order = []
        while True:
            job = self.sched.next()
            if job is None:
                break
            order.append(job.workflow_name)
            self.sched.complete(job.job_id)
        self.assertEqual(order, ["critical", "normal", "background"])

    def test_priority_overrides_arrival_order(self):
        self.sched.register("first_registered", interval_seconds=60, priority=1,
                            first_due_at=self.t0)
        self.sched.register("second_registered", interval_seconds=60, priority=99,
                            first_due_at=self.t0)
        self.sched.tick(now=self.t0)
        job = self.sched.next()
        self.assertEqual(job.workflow_name, "second_registered")
        self.sched.complete(job.job_id)

    def test_many_priorities_non_increasing_order(self):
        for i, p in enumerate([3, 1, 4, 1, 5, 9, 2, 6]):
            self.sched.register(f"t{i}", interval_seconds=60, priority=p,
                                first_due_at=self.t0)
        self.sched.tick(now=self.t0)
        priorities = []
        while True:
            job = self.sched.next()
            if job is None:
                break
            priorities.append(job.priority)
            self.sched.complete(job.job_id)
        for a, b in zip(priorities, priorities[1:]):
            self.assertGreaterEqual(a, b, "dispatch must be non-increasing by priority")


class TestDeadlineAwareAllocation(unittest.TestCase):
    """Deadline = due_time + max_delay_seconds; EDF breaks priority ties."""

    def setUp(self):
        self.sched = RecurringScheduler(max_concurrent=10)
        self.t0 = 3_000_000.0

    def test_job_deadline_equals_due_plus_max_delay(self):
        max_d = 120.0
        self.sched.register("t", interval_seconds=60, max_delay_seconds=max_d,
                            first_due_at=self.t0)
        jobs = self.sched.tick(now=self.t0)
        self.assertAlmostEqual(jobs[0].deadline, self.t0 + max_d, places=2)

    def test_earlier_deadline_dispatched_first_at_equal_priority(self):
        self.sched.register("urgent", interval_seconds=60, priority=5,
                            max_delay_seconds=30.0, first_due_at=self.t0)
        self.sched.register("relaxed", interval_seconds=60, priority=5,
                            max_delay_seconds=300.0, first_due_at=self.t0)
        self.sched.tick(now=self.t0)
        first = self.sched.next()
        self.assertEqual(first.workflow_name, "urgent")
        self.sched.complete(first.job_id)

    def test_three_way_edf_ordering(self):
        for name, md in [("c", 300.0), ("a", 10.0), ("b", 100.0)]:
            self.sched.register(name, interval_seconds=60, priority=2,
                                max_delay_seconds=md, first_due_at=self.t0)
        self.sched.tick(now=self.t0)
        order = []
        while True:
            job = self.sched.next()
            if job is None:
                break
            order.append(job.workflow_name)
            self.sched.complete(job.job_id)
        self.assertEqual(order, ["a", "b", "c"])

    def test_slot_cap_respected(self):
        sched = RecurringScheduler(max_concurrent=1)
        sched.register("a", interval_seconds=60, first_due_at=self.t0)
        sched.register("b", interval_seconds=60, first_due_at=self.t0)
        sched.tick(now=self.t0)
        j1 = sched.next()
        self.assertIsNotNone(j1)
        self.assertIsNone(sched.next())  # cap exhausted
        sched.complete(j1.job_id)
        j2 = sched.next()              # slot freed
        self.assertIsNotNone(j2)
        sched.complete(j2.job_id)

    def test_complete_releases_slot_immediately(self):
        sched = RecurringScheduler(max_concurrent=1)
        sched.register("only", interval_seconds=60, first_due_at=self.t0)
        sched.tick(now=self.t0)
        j = sched.next()
        self.assertFalse(sched.slot_available)
        sched.complete(j.job_id)
        self.assertTrue(sched.slot_available)


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


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2)
    sys.exit(0 if result.result.wasSuccessful() else 1)
