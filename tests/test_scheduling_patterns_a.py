"""Acceptance tests: recurring task scheduling patterns (st-090) — Part A.

Covers:
  - TestRegister: task registration and parameter storage.
  - TestTickEnqueue: tick() enqueues tasks exactly when their interval has elapsed.
  - TestPriorityOrdering: priority queue dispatches higher-urgency tasks first.
  - TestDeadlineAwareAllocation: deadline = due_time + max_delay_seconds; EDF tiebreak.

Split from test_scheduling_patterns.py (was 404 lines).
Run: python -m pytest tests/test_scheduling_patterns_a.py
"""
from __future__ import annotations

import sys
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


if __name__ == "__main__":
    result = unittest.main(exit=False, verbosity=2)
    sys.exit(0 if result.result.wasSuccessful() else 1)
