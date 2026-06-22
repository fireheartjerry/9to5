"""Aggregate run metrics from the task-state JSON store. Pure (reads files only)."""
from __future__ import annotations

import json
from datetime import datetime

import config
from state.task import TaskState

LOG = config.getLogger("metrics")
_TERMINAL = TaskState._TERMINAL
_SUCCESS = ("done", "complete")


def _duration(meta: dict, subs: list) -> "float | None":
    try:
        start = datetime.fromisoformat(meta["started_at"])
    except Exception:  # noqa: BLE001
        return None
    ends = []
    for s in subs:
        c = s.get("completed_at")
        if c:
            try:
                ends.append(datetime.fromisoformat(c))
            except Exception:  # noqa: BLE001
                pass
    if not ends:
        return None
    return max(0.0, (max(ends) - start).total_seconds())


def compute() -> dict:
    total = 0
    by_status: dict[str, int] = {}
    durations: list[float] = []
    subtasks_total = subtasks_passed = 0
    try:
        files = list(config.STATE_DIR.glob("*.json"))
    except Exception:  # noqa: BLE001
        files = []
    for f in files:
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            continue
        meta = data.get("meta", {})
        status = meta.get("status", "unknown")
        total += 1
        by_status[status] = by_status.get(status, 0) + 1
        subs = (data.get("plan", {}) or {}).get("subtasks", []) or []
        subtasks_total += sum(1 for s in subs if s.get("status") != "removed")
        subtasks_passed += sum(1 for s in subs if (s.get("verify_result") or {}).get("passed"))
        dur = _duration(meta, subs)
        if dur is not None:
            durations.append(dur)
    terminal = sum(v for k, v in by_status.items() if k in _TERMINAL)
    success = sum(v for k, v in by_status.items() if k in _SUCCESS)
    return {
        "total_runs": total,
        "by_status": by_status,
        "terminal_runs": terminal,
        "success_runs": success,
        "success_rate": round(success / terminal, 3) if terminal else None,
        "avg_duration_seconds": round(sum(durations) / len(durations), 1) if durations else None,
        "subtasks_total": subtasks_total,
        "subtasks_passed": subtasks_passed,
    }
