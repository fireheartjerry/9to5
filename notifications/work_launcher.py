"""Pure launcher core for the Discord /work command. No discord import -> unit-testable.
Builds an argv for main.py and spawns it as a detached child so the gateway stays
responsive and a bot restart never kills an in-flight run.
"""
from __future__ import annotations

import math
import os
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

import config
from notifications import commands
from state.task import TaskState

LOG = config.getLogger("work_launcher")

HOURS_MIN: float = 0.1
HOURS_MAX: float = 24.0
MAX_PARALLEL: int = 4
MAX_GOAL_CHARS: int = 6000
VALID_MODES = ("watch", "gated")


@dataclass
class WorkRequest:
    goal: str
    hours: float = 1.0
    mode: str = "watch"
    parallel: int = 1
    work_dir: Optional[str] = None
    no_pr: bool = False
    night_mode: bool = False


def parseHours(raw) -> float:
    """Tolerant parse ('2', '2h', '1.5'); empty/invalid -> 1.0; clamp to [HOURS_MIN, HOURS_MAX]."""
    if raw is None:
        return 1.0
    if isinstance(raw, (int, float)):
        val = float(raw)
    else:
        s = str(raw).strip().lower().rstrip("h").strip()
        try:
            val = float(s)
        except ValueError:
            return 1.0
    if not math.isfinite(val):
        return 1.0
    return max(HOURS_MIN, min(HOURS_MAX, val))


def validate(req: WorkRequest) -> list[str]:
    errs: list[str] = []
    if not (req.goal or "").strip():
        errs.append("Goal is required.")
    if len((req.goal or "")) > MAX_GOAL_CHARS:
        errs.append(f"Goal too long (>{MAX_GOAL_CHARS} chars).")
    if not (HOURS_MIN <= req.hours <= HOURS_MAX):
        errs.append(f"Hours must be between {HOURS_MIN} and {HOURS_MAX}.")
    if req.mode not in VALID_MODES:
        errs.append(f"Mode must be one of {VALID_MODES}.")
    if not (1 <= req.parallel <= MAX_PARALLEL):
        errs.append(f"Parallel must be between 1 and {MAX_PARALLEL}.")
    if req.work_dir and not Path(req.work_dir).is_dir():
        errs.append(f"work_dir does not exist or is not a directory: {req.work_dir}")
    return errs


def buildArgv(req: WorkRequest) -> list[str]:
    argv = [
        str(config.VENV_PYTHON), str(config.PROJECT_ROOT / "main.py"),
        "--goal", req.goal,
        "--hours", str(req.hours),
        "--auto-approve",
        "--mode", req.mode,
        "--parallel", str(req.parallel),
    ]
    if req.no_pr:
        argv.append("--no-pr")
    if req.night_mode:
        argv.append("--night-mode")
    if req.work_dir:
        argv += ["--work-dir", str(Path(req.work_dir).resolve())]
    return argv


def activeRun() -> Optional[TaskState]:
    """The latest task iff it's still active. Auto-aborts stale tasks whose process died
    without updating state (e.g. killed mid-elaboration, left in 'created'/'planning')."""
    state = commands.resolveTargetTask()
    if not commands.isRunActive(state):
        return None
    if _isStale(state):
        try:
            state.setStatus("aborted")
            LOG.warning("auto-aborted stale task %s (no heartbeat for >%ds)",
                        state.task_id[:8], _STALE_SECONDS)
        except Exception:  # noqa: BLE001
            pass
        return None
    return state


# A task is stale if its state file hasn't been touched in this many seconds.
# 'created' tasks (died in elaboration) stale out faster; executing tasks use RUN_STALL_SECONDS.
_STALE_CREATED_SECONDS: int = 300    # 5 min — elaboration should never take this long
_STALE_SECONDS: int = int(getattr(config, "RUN_STALL_SECONDS", 1800))


def _isStale(state: Optional[TaskState]) -> bool:
    """True when a task's state file mtime implies the orchestrator process is dead."""
    if state is None:
        return False
    try:
        mtime = (config.STATE_DIR / f"{state.task_id}.json").stat().st_mtime
        age = time.time() - mtime
        cutoff = (_STALE_CREATED_SECONDS if state.meta.get("status") in ("created", "planning")
                  else _STALE_SECONDS)
        return age > cutoff
    except OSError:
        return False


def newestTaskSince(ts: float) -> Optional[str]:
    """task_id of the newest state file created at/after `ts` (with ~2s mtime fuzz for filesystem coarseness) (used to confirm a launch)."""
    best_id, best_m = None, ts - 1
    try:
        for f in config.STATE_DIR.glob("*.json"):
            m = f.stat().st_mtime
            if m >= ts - 2.0 and m > best_m:
                best_m, best_id = m, f.stem
    except OSError:
        return None
    return best_id


def _spawnArgv(argv: list[str], tag: str) -> int:
    """Spawn argv as a DETACHED child (survives a bot restart). Returns the child PID."""
    config.LOG_PATH.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    logfile = open(config.LOG_PATH / f"{tag}-{stamp}.log", "a", encoding="utf-8", errors="replace")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        argv, cwd=str(config.PROJECT_ROOT),
        stdin=subprocess.DEVNULL, stdout=logfile, stderr=subprocess.STDOUT,
        close_fds=True, creationflags=creationflags,
    )
    logfile.close()   # child keeps its own duplicated handle; release the parent's copy
    LOG.info("Spawned %s pid=%s", tag, proc.pid)
    return proc.pid


def spawn(req: WorkRequest) -> int:
    return _spawnArgv(buildArgv(req), "work")


def buildResumeArgv(task_id: str) -> list[str]:
    return [str(config.VENV_PYTHON), str(config.PROJECT_ROOT / "main.py"), "--resume", task_id]


def taskExists(task_id: str) -> bool:
    return (config.STATE_DIR / f"{task_id}.json").exists()


def spawnResume(task_id: str) -> int:
    return _spawnArgv(buildResumeArgv(task_id), "resume")


def launchOrError(req: WorkRequest) -> str:
    """Validate -> block-if-active -> spawn -> confirm. Returns the user-facing message.
    BLOCKING (Popen + up to ~10s poll); async callers must run via asyncio.to_thread."""
    errs = validate(req)
    if errs:
        return "❌ " + "  ".join(errs)
    active = activeRun()
    if active is not None:
        return (f"⛔ A run is already active (`{active.task_id[:8]}` · "
                f"`{active.meta.get('status')}`). Abort it first.")
    t0 = time.time()
    try:
        pid = spawn(req)
    except Exception as e:  # noqa: BLE001
        LOG.exception("spawn failed")
        return f"❌ Launch failed: {e}"
    task_id = None
    for _ in range(20):
        task_id = newestTaskSince(t0)
        if task_id:
            break
        time.sleep(0.5)
    web = f"http://127.0.0.1:{config.WEB_DASHBOARD_PORT}/"
    if task_id:
        return (f"✅ Launched run `{task_id[:8]}` (pid {pid}) · mode `{req.mode}` · "
                f"{req.hours}h · parallel {req.parallel}\n{web}")
    return (f"✅ Launch started (pid {pid}) · mode `{req.mode}` · {req.hours}h. "
            f"If no dashboard appears shortly, check `logs\\work-*.log`.\n{web}")


def resumeOrError(task_id: str) -> str:
    """Resume an existing task by id (block if a run is active). Returns the user message."""
    if not taskExists(task_id):
        return f"❌ No such task `{task_id}`."
    active = activeRun()
    if active is not None:
        return f"⛔ A run is already active (`{active.task_id[:8]}`). Abort it first."
    try:
        pid = spawnResume(task_id)
    except Exception as e:  # noqa: BLE001
        LOG.exception("resume spawn failed")
        return f"❌ Resume failed: {e}"
    web = f"http://127.0.0.1:{config.WEB_DASHBOARD_PORT}/"
    return f"♻️ Resuming `{task_id[:8]}` (pid {pid})\n{web}"
