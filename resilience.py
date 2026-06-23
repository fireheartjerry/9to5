"""Run supervision & resilience -- the backbone of the 9am->5pm promise.

The product promise is: send one sentence at 9am, come back at 5pm to a finished job. That
only holds if the run survives crashes, hangs, and time pressure WITHOUT a human. This
module supervises a run:

  * **Crash auto-recovery** -- if ``runFull`` raises or the process dies, resume the same
    task (bounded restarts, exponential backoff), never losing committed progress.
  * **Deadline awareness** -- stop retrying once the 5pm horizon passes; the orchestrator
    already finalizes whatever is done as a deliverable.
  * **Orphan resume** -- on a fresh process, pick up an interrupted non-terminal task.
  * **Stall detection** -- surface a run that has made no progress for too long.

Pure + dependency-light so the recovery logic is fully unit-testable offline.
"""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Callable, Optional

import config
from state.task import TaskState

LOG = config.getLogger("resilience")

_TERMINAL = ("done", "complete", "aborted", "partial", "blocked", "failed")


def remaining_seconds(state: TaskState) -> Optional[float]:
    """Seconds until the deadline (negative once passed); None if unparseable."""
    deadline = state.meta.get("deadline_at")
    if not deadline:
        return None
    try:
        return (datetime.fromisoformat(deadline) - datetime.now().astimezone()).total_seconds()
    except Exception:  # noqa: BLE001
        return None


def deadline_passed(state: TaskState) -> bool:
    rem = remaining_seconds(state)
    return rem is not None and rem <= 0


def is_terminal(state: TaskState) -> bool:
    return state.meta.get("status") in _TERMINAL


def last_progress_at(state: TaskState) -> Optional[str]:
    """ISO timestamp of the most recent subtask completion (progress heartbeat)."""
    times = [s.get("completed_at") for s in state.subtasks if s.get("completed_at")]
    return max(times) if times else state.meta.get("started_at")


def is_stalled(state: TaskState, *, max_idle_seconds: float) -> bool:
    """True if no subtask has completed within ``max_idle_seconds`` (a hung run)."""
    ts = last_progress_at(state)
    if not ts:
        return False
    try:
        idle = (datetime.now().astimezone() - datetime.fromisoformat(ts)).total_seconds()
    except Exception:  # noqa: BLE001
        return False
    return idle >= max_idle_seconds


def pick_resume_task() -> Optional[str]:
    """The most-recent interrupted (non-terminal) task to auto-resume, or None."""
    latest = TaskState.loadLatest()
    if latest is not None and not is_terminal(latest):
        return latest.task_id
    return None


def run_with_recovery(run_fn: Callable[[TaskState], dict], state: TaskState, *,
                      max_restarts: Optional[int] = None, backoff_base: float = 2.0,
                      sleep: Callable[[float], None] = time.sleep,
                      reload_state: Optional[Callable[[str], TaskState]] = None) -> dict:
    """Run ``run_fn(state)`` and auto-resume it on crash until the task is terminal, the
    deadline passes, or the restart budget is exhausted. Returns the final summary.

    ``run_fn`` is the orchestrator's runFull (bound to its work_dir/args). On a raised
    exception or a non-terminal return, we reload the persisted state (committed progress
    is the source of truth) and try again after exponential backoff.
    """
    max_restarts = config.RUN_MAX_RESTARTS if max_restarts is None else max_restarts
    reload_state = reload_state or TaskState.load
    attempt = 0
    no_progress_streak = 0
    prev_progress = last_progress_at(state)
    last_summary: dict[str, Any] = {"task_id": state.task_id, "status": "unknown"}

    while True:
        try:
            last_summary = run_fn(state) or last_summary
        except Exception as e:  # noqa: BLE001 -- a crash must become a resume, not a death
            LOG.error("run crashed (attempt %d): %s", attempt + 1, e, exc_info=True)
            last_summary = {"task_id": state.task_id, "status": "crashed", "error": str(e)}

        try:
            state = reload_state(state.task_id)   # adopt committed progress before deciding
        except Exception:  # noqa: BLE001
            pass

        if is_terminal(state):
            return last_summary
        if deadline_passed(state):
            LOG.warning("deadline passed; finalizing without further restarts")
            _finalize_partial(state)
            return {"task_id": state.task_id, "status": state.meta.get("status", "partial"),
                    "reason": "deadline"}

        attempt += 1
        # PROGRESS-AWARE, HORIZON-SCALED budget (CB-13): a restart that completed new subtasks resets
        # the streak, so a run that keeps making headway is NEVER abandoned before the deadline -- only
        # a run that crashes WITHOUT progress repeatedly (a deterministic crash) burns the budget. The
        # budget also scales with the time left (~1 retry / 15 min) so an early crash doesn't strand an
        # 8h run dead at 09:02; backoff grows up to RUN_RESTART_MAX_BACKOFF so we never hot-spin.
        cur_progress = last_progress_at(state)
        no_progress_streak = 0 if cur_progress != prev_progress else no_progress_streak + 1
        prev_progress = cur_progress
        rem = remaining_seconds(state) or 0
        budget = max(max_restarts, int(rem // 900))
        if no_progress_streak > budget:
            LOG.error("exhausted %d no-progress restarts (budget %d); leaving task blocked",
                      no_progress_streak, budget)
            _finalize_partial(state, status="blocked", reason="restart budget exhausted (no progress)")
            return {"task_id": state.task_id, "status": "blocked", "reason": "max_restarts"}
        delay = min(backoff_base ** min(no_progress_streak, 12), config.RUN_RESTART_MAX_BACKOFF)
        LOG.warning("resuming task %s in %.0fs (restart %d, no-progress streak %d/%d)",
                    state.task_id, delay, attempt, no_progress_streak, budget)
        sleep(delay)


def _finalize_partial(state: TaskState, *, status: str = "partial",
                      reason: str = "") -> None:
    """Best-effort: mark a non-terminal interrupted run as a deliverable, never crash."""
    try:
        if state.meta.get("status") not in _TERMINAL:
            state.setStatus(status, blocked_reason=reason or None)
    except Exception as e:  # noqa: BLE001
        LOG.debug("finalize_partial failed (ignored): %s", e)
