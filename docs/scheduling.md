# 9TO5 — Recurring Task Scheduling Patterns

> **Module:** `scheduling/`
> **Acceptance SLA:** average start delay < 300 s (5 minutes)
> **Run/test:** `python C:\9to5\tests\test_scheduling_patterns.py`

---

## Overview

The scheduling layer ensures recurring tasks (health checks, dashboard polls,
alert scans) start within 5 minutes of their due time.  It wraps the underlying
`workflows/scheduler.py` priority queue, adding:

- per-task interval tracking and re-enqueue logic
- deadline-aware slot allocation (EDF tiebreaking)
- SLA delay tracking (`average_delay_seconds()`)
- overdue-job detection (`overdue_jobs()`)

---

## Architecture

```
RecurringScheduler  (scheduling/recurring.py)
  │
  │  register(task_id, interval_seconds, priority, max_delay_seconds)
  │  tick(now)   ──→ enqueue due tasks into ▼
  │  next()      ──→ dispatch highest-priority / earliest-deadline
  │  complete()  ──→ record delay, free slot
  │
  └── WorkflowScheduler  (workflows/scheduler.py)
        min-heap: (neg_priority, deadline, enqueued_at, job_id)
        threading.Lock on every public method
        max_concurrent slot cap
```

---

## Key patterns

### 1. Priority + Earliest-Deadline-First (EDF)

Jobs are dispatched in this order:

1. **Highest `priority`** — explicit urgency signal (larger int = more urgent)
2. **Earliest `deadline`** — EDF tiebreaker when priority is equal
3. **Earliest `enqueued_at`** — FIFO tiebreaker for identical priority + deadline

```python
# deadline = due_time + max_delay_seconds
deadline = next_due + task.max_delay_seconds
job = scheduler.enqueue(task_id, priority=p, deadline=deadline)
```

The 5-minute default (`MAX_DELAY_SECONDS = 300.0`) gives every task a 300-second
window after its due time before it becomes overdue.

### 2. Fixed-interval re-enqueue

`tick(now)` advances each task's `_last_due_at` by exactly one `interval_seconds`
per call.  This prevents thundering-herd catch-up when the system restarts after
downtime: a task that is 3 intervals late fires exactly once.

```python
next_due = task._last_due_at + task.interval_seconds
if now >= next_due:
    task._last_due_at = next_due   # advance by ONE interval only
    enqueue(...)
```

### 3. Slot-cap concurrency control

`WorkflowScheduler(max_concurrent=N)` caps simultaneous executions.  `next()`
returns `None` when all N slots are occupied — the caller must wait and retry.

```python
sched = RecurringScheduler(max_concurrent=4)
job = sched.next()    # None if all slots full
```

### 4. SLA delay tracking

Every `complete(job_id)` records `max(0, started_at − due_at)` in `_delays`.
`average_delay_seconds()` computes the mean across all completions.
A healthy system stays well below 300 s; a spike here indicates slot starvation.

```python
avg = sched.average_delay_seconds()   # 0.0 if no completions yet
assert avg < MAX_DELAY_SECONDS        # SLA check
```

### 5. Overdue-job detection

`overdue_jobs()` surfaces queued-but-not-started jobs whose `deadline < now`.
Callers should alert or cancel these to prevent queue pileup.

```python
for job in sched.overdue_jobs():
    logger.warning("overdue: %s deadline=%s", job.job_id, job.deadline)
    sched.cancel(job.job_id)   # optional: drop unrecoverable jobs
```

---

## Concurrency safety

`WorkflowScheduler` holds a single `threading.Lock` across all public methods.
`RecurringScheduler` delegates all state mutation to `WorkflowScheduler`, so it
inherits the same thread-safety guarantee without a second lock.

---

## Recommended operating parameters

| Task class | `interval_seconds` | `priority` | `max_delay_seconds` |
|---|---|---|---|
| Health check | 60 | 10 | 120 |
| Dashboard refresh | 30 | 8 | 60 |
| Alert scan | 120 | 9 | 240 |
| Metrics flush | 300 | 5 | 300 |
| Background GC | 600 | 1 | 300 |

Rationale: critical health/alert tasks get higher priority AND tighter deadline
windows so EDF scheduling naturally promotes them over background jobs.

---

## Failure modes and mitigations

| Failure | Root cause | Mitigation |
|---|---|---|
| Average delay > 300 s | Slot starvation — `max_concurrent` too low | Raise `max_concurrent`; shed low-priority tasks via `cancel()` |
| Overdue jobs pile up | Tasks fire faster than slots free | Drain via `overdue_jobs()` + `cancel()`; alert on queue depth |
| Missed intervals on restart | Task not re-registered after crash | Re-register with `first_due_at=time.time()` on startup |
| Double-fire after clock jump | `now` jumps backward (NTP slew) | Pass monotonic `time.monotonic()` as `now` in clock-sensitive contexts |

---

## Module layout

| File | Role |
|---|---|
| `scheduling/__init__.py` | Re-exports `RecurringScheduler`, `RecurringTask`, `MAX_DELAY_SECONDS` |
| `scheduling/recurring.py` | Interval tracking, enqueue logic, delay metrics — wraps `WorkflowScheduler` |
| `workflows/scheduler.py` | Priority min-heap, EDF tiebreaking, slot cap, thread-safe ops |
| `tests/test_scheduling_patterns.py` | 38 acceptance tests covering all patterns above |

---

## Changes introduced in st-090 and team benefits

### What was built

This subtask created the `scheduling/` package from scratch as the canonical
recurring-task layer for 9TO5.  Before this work, task timing relied on ad-hoc
`time.sleep` loops scattered across orchestrator code with no SLA enforcement or
delay visibility.

| Improvement | Before | After |
|---|---|---|
| Delay guarantee | none — tasks fire when the loop gets to them | SLA-enforced: `average_delay_seconds() < 300 s` |
| Dispatch order | FIFO (arrival order) | Priority + EDF — critical tasks promoted automatically |
| Overdue detection | none | `overdue_jobs()` surfaces stale queue entries for cancellation |
| Double-fire on restart | possible — no interval tracking | Prevented — `_last_due_at` advances by exactly one interval per tick |
| Concurrency control | unbounded | `max_concurrent` slot cap; `next()` returns `None` when full |
| Testability | not unit-testable (wall-clock sleeps) | Fully deterministic — `tick(now=<float>)` replaces wall clock in tests |

### How the team benefits

1. **Reliability SLA** — `average_delay_seconds()` is a single number to monitor.
   Wire it into the active alerting system (`monitoring/alerter.py`) for automatic
   Discord alerts when recurring tasks fall behind.

2. **Priority control** — raising `priority` on a task bumps it ahead of all
   lower-priority jobs without changing any other code.  Operationally useful
   during incident response.

3. **No thundering-herd on restart** — fixed-interval re-enqueue means a task that
   is 10 intervals late fires exactly once, not 10 times in rapid succession.

4. **Integration path** — import `RecurringScheduler` from the `scheduling` package
   and drop it into the orchestrator loop in place of `time.sleep` calls.

---

## Usage example

```python
from scheduling import RecurringScheduler

sched = RecurringScheduler(max_concurrent=4)

sched.register("health-check",   interval_seconds=60,  priority=10, max_delay_seconds=120.0)
sched.register("alert-scan",     interval_seconds=120, priority=9,  max_delay_seconds=240.0)
sched.register("metrics-flush",  interval_seconds=300, priority=5)

while True:
    sched.tick()              # enqueue any due tasks
    job = sched.next()        # dispatch next eligible job
    if job:
        run_workflow(job.workflow_name)
        sched.complete(job.job_id)
    for j in sched.overdue_jobs():
        logger.warning("overdue: %s", j.job_id)
    time.sleep(1)

assert sched.average_delay_seconds() < 300.0   # SLA guard
```
