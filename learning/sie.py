"""Self-Improvement Orchestrator -- the component that runs the learning loop A->Z
*automatically*, so the human only ever starts / aborts / checks.

Product philosophy: the user does as little as possible. They never run a consolidation
script or trigger a policy rebuild -- the system maintains itself. This module is the
cadence ladder:

  * **Per-run (every task):** fired from the orchestrator's ``finally`` block, so it runs
    on success, abort, or failure -- no schedule, no human.
  * **Throttled tiers:** the heavy passes (consolidation, policy rebuild, embedding
    backfill, eval) run at most once per window (default daily) -- a timestamp file makes
    "daily" work without any cron, on whatever cadence the user actually runs tasks.

Everything is **best-effort and file-locked**: a maintenance failure can never affect a
run, and two overlapping runs can't double-process. See the spec (meta-loop / X1).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import config
from memory import experience

LOG = config.getLogger("sie.orchestrator")

# Heavy passes run at most once per this window (seconds). "Daily" without a scheduler.
DEFAULT_THROTTLE_SECONDS = 12 * 3600
# Prompt/policy promotion is a slower tier -- it needs many field uses to accumulate.
WEEKLY_THROTTLE_SECONDS = 7 * 24 * 3600


def _state_path() -> Path:
    return Path(config.CONTROL_DIR) / "sie_state.json"


def _lock_path() -> Path:
    return Path(config.CONTROL_DIR) / "sie_maintenance.lock"


def _read_state() -> dict[str, Any]:
    try:
        return json.loads(_state_path().read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 -- missing/corrupt -> start fresh
        return {}


def _write_state(data: dict[str, Any]) -> None:
    try:
        p = _state_path()
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        LOG.warning("sie state write failed (ignored): %s", e)


def _acquire_lock() -> Optional[Path]:
    """O_EXCL lock so two concurrent runs never run maintenance at once. A stale lock
    (>1h, e.g. a crashed pass) is reclaimed. Returns the lock path, or None if held."""
    lp = _lock_path()
    try:
        lp.parent.mkdir(parents=True, exist_ok=True)
        if lp.exists() and time.time() - lp.stat().st_mtime > 3600:
            lp.unlink(missing_ok=True)  # reclaim a stale lock
        fd = os.open(str(lp), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        os.write(fd, str(os.getpid()).encode())
        os.close(fd)
        return lp
    except FileExistsError:
        return None
    except Exception as e:  # noqa: BLE001
        LOG.debug("sie lock unavailable (ignored): %s", e)
        return None


def _due(state: dict[str, Any], throttle_seconds: float) -> bool:
    last = state.get("last_full_at")
    if not last:
        return True
    try:
        elapsed = (datetime.now().astimezone() - datetime.fromisoformat(last)).total_seconds()
    except Exception:  # noqa: BLE001
        return True
    return elapsed >= throttle_seconds


def run_maintenance(*, reason: str = "post-run", force: bool = False,
                    throttle_seconds: float = DEFAULT_THROTTLE_SECONDS,
                    db_path: Optional[Path] = None) -> dict[str, Any]:
    """Run the throttled learning passes once (idempotent, best-effort, locked).

    Returns a summary dict. ``skipped`` reasons: ``kill_switch`` (SIE off), ``not_due``
    (throttled), ``locked`` (another run is mid-maintenance). Never raises.
    """
    if config.SIE_KILL_SWITCH:
        return {"skipped": "kill_switch"}
    state = _read_state()
    if not force and not _due(state, throttle_seconds):
        return {"skipped": "not_due", "last_full_at": state.get("last_full_at")}

    lock = _acquire_lock()
    if lock is None:
        return {"skipped": "locked"}
    summary: dict[str, Any] = {"reason": reason, "ran_at": datetime.now().astimezone().isoformat(timespec="seconds")}
    try:
        experience.init(db_path)
        summary["steps"] = {}
        steps = list(_maintenance_steps(db_path))
        # The weekly tier (prompt/policy promotion) rides on the same pass but only when
        # its slower window is due -- so promotion is automatic yet never premature.
        weekly_due = force or _weekly_due(state)
        if weekly_due:
            steps += list(_weekly_steps(db_path))
        # Each step is independent + best-effort: one failing never blocks the others.
        for name, fn in steps:
            try:
                summary["steps"][name] = fn()
            except Exception as e:  # noqa: BLE001
                LOG.warning("sie step %s failed (ignored): %s", name, e)
                summary["steps"][name] = {"error": str(e)}
        state["last_full_at"] = summary["ran_at"]
        if weekly_due:
            state["last_weekly_at"] = summary["ran_at"]
        state["runs"] = int(state.get("runs", 0)) + 1
        _write_state(state)
        LOG.info("sie maintenance done (%s): %s", reason, summary["steps"])
        return summary
    finally:
        try:
            Path(lock).unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


def _maintenance_steps(db_path: Optional[Path]):
    """The ordered learning passes. Imported lazily so a heavy/broken submodule can't
    taint module load, and so future phases (promotion, LoRA) append here cleanly."""
    def embeddings():
        from memory import retrieval
        return retrieval.backfill_embeddings(db_path=db_path)

    def consolidate():
        from learning import lessons
        return lessons.consolidate(db_path=db_path, write_digest=True)

    def policy_rebuild():
        from learning import policy
        return policy.rebuild_from_ledger(db_path=db_path)

    def evaluate():
        from learning import eval_harness
        # No live brain in every environment -> records a transparent marker; a wired
        # runner (later phases) produces a real fitness point automatically.
        return eval_harness.run_suite(runner=None, db_path=db_path)

    return [
        ("embeddings", embeddings),
        ("consolidate", consolidate),
        ("policy_rebuild", policy_rebuild),
        ("evaluate", evaluate),
    ]


def _weekly_due(state: dict[str, Any]) -> bool:
    last = state.get("last_weekly_at")
    if not last:
        return True
    try:
        elapsed = (datetime.now().astimezone() - datetime.fromisoformat(last)).total_seconds()
    except Exception:  # noqa: BLE001
        return True
    return elapsed >= WEEKLY_THROTTLE_SECONDS


def _weekly_steps(db_path: Optional[Path]):
    """Slower tier: prompt (and later adapter) promotion -- gated by the eval harness +
    field metrics, never premature. Runs automatically; the human only start/abort/checks."""
    def prompt_promotion():
        from learning import promotion
        return promotion.run_promotions(db_path=db_path)

    return [("prompt_promotion", prompt_promotion)]


def run_maintenance_async(**kwargs) -> None:
    """Fire-and-forget maintenance on a daemon thread so it never adds latency to the
    run's teardown. Best-effort: swallows everything."""
    import threading

    def _bg():
        try:
            run_maintenance(**kwargs)
        except Exception as e:  # noqa: BLE001
            LOG.debug("async maintenance failed (ignored): %s", e)

    threading.Thread(target=_bg, name="sie-maintenance", daemon=True).start()


if __name__ == "__main__":  # pragma: no cover -- manual full pass
    print(run_maintenance(reason="manual", force=True))
