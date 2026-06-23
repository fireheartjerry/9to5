"""Autonomous self-play -- the system practices its own weaknesses without being asked.

Curriculum (subsystem C) authors practice goals for the weakest task families; this
*executes* them. When the engine is idle and inside the work window, it launches the top
self-generated goal as a normal 9TO5 run -- bounded by a per-day cap so it never runs away.
This is the difference between "suggests practice" and "actually practices."

The launch itself goes through an injectable seam (``launch_fn``) so it is offline-testable
and so it reuses the existing work launcher in production. Best-effort; never raises.

See the spec (subsystem C + meta-loop).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional

import config
from learning import curriculum

LOG = config.getLogger("sie.selfplay")

LaunchFn = Callable[[str, float], Any]   # (goal_text, hours) -> anything


def _state_path() -> Path:
    return Path(config.CONTROL_DIR) / "selfplay_state.json"


def _today() -> str:
    return datetime.now().astimezone().strftime("%Y-%m-%d")


def _count_today() -> int:
    try:
        data = json.loads(_state_path().read_text(encoding="utf-8"))
        return int(data.get(_today(), 0))
    except Exception:  # noqa: BLE001
        return 0


def _bump_today() -> None:
    try:
        p = _state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
        data = {_today(): int(data.get(_today(), 0)) + 1}   # keep only today
        p.write_text(json.dumps(data), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        LOG.debug("selfplay state bump failed (ignored): %s", e)


def in_work_window(now: Optional[datetime] = None) -> bool:
    """Self-play only fires inside the configured work window (default 9-17, the 9-to-5)."""
    now = now or datetime.now().astimezone()
    return config.SELFPLAY_START_HOUR <= now.hour < config.SELFPLAY_END_HOUR


def run(*, launch_fn: Optional[LaunchFn] = None, is_busy: Optional[Callable[[], bool]] = None,
        db_path: Optional[Path] = None, now: Optional[datetime] = None) -> dict[str, Any]:
    """Maybe launch one self-play run. Returns a status dict; never raises.

    Gates (all must hold): enabled, in the work window, not already busy, under the daily
    cap, and there is a weak family worth practicing.
    """
    if not config.SELFPLAY_ENABLED:
        return {"skipped": "disabled"}
    if not in_work_window(now):
        return {"skipped": "outside_window"}
    if is_busy is not None and is_busy():
        return {"skipped": "busy"}              # never compete with the user's own run
    if _count_today() >= config.SELFPLAY_MAX_PER_DAY:
        return {"skipped": "daily_cap"}
    goals = curriculum.generate_goals(n=1, db_path=db_path)
    if not goals:
        return {"skipped": "no_weak_family"}
    goal = goals[0]
    if launch_fn is None:
        return {"skipped": "no_launcher", "would_run": goal["goal"]}
    try:
        launch_fn(goal["goal"], float(config.SELFPLAY_HOURS))
        _bump_today()
        LOG.info("self-play launched: %s", goal["goal"])
        return {"launched": goal["goal"], "family": goal["family"]}
    except Exception as e:  # noqa: BLE001
        LOG.warning("self-play launch failed (ignored): %s", e)
        return {"error": str(e)}
