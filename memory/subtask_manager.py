"""Higher-level subtask management helpers built on the Experience Ledger.

Provides aggregation, status-filtering, and convenience mutators that
orchestrator / webdash / command_bot can use without touching raw SQL.
Everything here is best-effort: failures degrade to empty/False results,
never exceptions, so the calling run is never blocked.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Optional

import config
from memory import experience

LOG = config.getLogger("sie.subtask_manager")

# Terminal statuses -- a subtask in one of these is considered finished.
TERMINAL_STATUSES: frozenset[str] = frozenset(
    {"done", "complete", "failed", "aborted", "blocked", "skipped"}
)

# Passing statuses -- subtasks we count as successful.
PASSING_STATUSES: frozenset[str] = frozenset({"done", "complete"})


@dataclass
class SubtaskStats:
    """Aggregated metrics for all subtasks belonging to a run."""

    run_id: str
    total: int = 0
    passed: int = 0
    failed: int = 0
    pending: int = 0
    skipped: int = 0
    total_attempts: int = 0
    # status_counts holds exact counts for every status seen
    status_counts: dict[str, int] = field(default_factory=dict)

    @property
    def pass_rate(self) -> float:
        """Fraction of terminal subtasks that passed; 0.0 if none finished."""
        finished = self.passed + self.failed + self.skipped
        return self.passed / finished if finished > 0 else 0.0

    @property
    def avg_attempts(self) -> float:
        """Mean attempt count across all subtasks that have one recorded."""
        return self.total_attempts / self.total if self.total > 0 else 0.0


def getRunStats(run_id: str, *, db_path: Optional[Path] = None) -> Optional[SubtaskStats]:
    """Compute aggregated stats for every subtask in *run_id*.

    Returns None when run_id is blank or the ledger is disabled/unavailable.
    Returns a zeroed SubtaskStats when the run exists but has no subtasks yet.
    """
    if not (run_id or "").strip():
        LOG.warning("getRunStats: missing or empty run_id")
        return None
    if not config.EXPERIENCE_LEDGER_ENABLED:
        return None
    try:
        rows = experience.fetch_subtasks(run_id, db_path=db_path)
        stats = SubtaskStats(run_id=run_id)
        for row in rows:
            stats.total += 1
            status = (row.get("status") or "").lower()
            stats.status_counts[status] = stats.status_counts.get(status, 0) + 1

            verify_passed = row.get("verify_passed")
            if verify_passed == 1:
                stats.passed += 1
            elif status in ("failed", "aborted"):
                stats.failed += 1
            elif status in ("blocked", "skipped"):
                stats.skipped += 1
            elif status not in TERMINAL_STATUSES:
                stats.pending += 1
            else:
                # terminal but not passed and not categorised above
                stats.failed += 1

            attempt_count = row.get("attempt_count")
            if attempt_count is not None:
                try:
                    stats.total_attempts += int(float(attempt_count))
                except (TypeError, ValueError):
                    pass
        return stats
    except Exception as exc:  # noqa: BLE001 -- never crash the caller
        LOG.warning("getRunStats failed (ignored): %s", exc)
        return None


def getPassRate(run_id: str, *, db_path: Optional[Path] = None) -> float:
    """Shorthand: pass-rate for *run_id* (0.0 on error or no data)."""
    stats = getRunStats(run_id, db_path=db_path)
    return stats.pass_rate if stats is not None else 0.0


def pendingSubtasks(run_id: str, *,
                    db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Return subtasks for *run_id* whose status is not in TERMINAL_STATUSES.

    Returns [] on any error.
    """
    if not (run_id or "").strip():
        LOG.warning("pendingSubtasks: missing or empty run_id")
        return []
    try:
        rows = experience.fetch_subtasks(run_id, db_path=db_path)
        return [
            r for r in rows
            if (r.get("status") or "").lower() not in TERMINAL_STATUSES
        ]
    except Exception as exc:  # noqa: BLE001
        LOG.warning("pendingSubtasks failed (ignored): %s", exc)
        return []


def filterByStatus(run_id: str, status: str, *,
                   db_path: Optional[Path] = None) -> list[dict[str, Any]]:
    """Return subtasks for *run_id* whose status equals *status* (case-insensitive).

    Returns [] on any error or blank inputs.
    """
    if not (run_id or "").strip():
        LOG.warning("filterByStatus: missing or empty run_id")
        return []
    if not (status or "").strip():
        LOG.warning("filterByStatus: missing or empty status")
        return []
    target = status.strip().lower()
    try:
        rows = experience.fetch_subtasks(run_id, db_path=db_path)
        return [r for r in rows if (r.get("status") or "").lower() == target]
    except Exception as exc:  # noqa: BLE001
        LOG.warning("filterByStatus failed (ignored): %s", exc)
        return []


def markDone(run_id: str, st_id: str, *,
             db_path: Optional[Path] = None) -> bool:
    """Mark a subtask as done (verify_passed=1, status='done'). Best-effort."""
    return _setStatus(run_id, st_id, "done", verify_passed=True, db_path=db_path)


def markFailed(run_id: str, st_id: str, *,
               db_path: Optional[Path] = None) -> bool:
    """Mark a subtask as failed (verify_passed=0, status='failed'). Best-effort."""
    return _setStatus(run_id, st_id, "failed", verify_passed=False, db_path=db_path)


def markSkipped(run_id: str, st_id: str, *,
                db_path: Optional[Path] = None) -> bool:
    """Mark a subtask as skipped. Best-effort."""
    return _setStatus(run_id, st_id, "skipped", verify_passed=None, db_path=db_path)


# ------------------------------------------------------------------ internals

def _setStatus(run_id: str, st_id: str, status: str, *,
               verify_passed: Optional[bool],
               db_path: Optional[Path] = None) -> bool:
    """Shared upsert helper for the markX convenience functions."""
    if not (run_id or "").strip():
        LOG.warning("_setStatus: missing or empty run_id")
        return False
    if not (st_id or "").strip():
        LOG.warning("_setStatus: missing or empty st_id")
        return False
    st: dict[str, Any] = {
        "subtask_id": st_id,
        "status": status,
        "verify_result": {"passed": verify_passed} if verify_passed is not None else {},
    }
    return experience.record_subtask(run_id, st, db_path=db_path)
