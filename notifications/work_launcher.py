"""Pure launcher core for the Discord /work command. No discord import -> unit-testable.
Builds an argv for main.py and spawns it as a detached child so the gateway stays
responsive and a bot restart never kills an in-flight run.
"""
from __future__ import annotations

import math
import os
import subprocess
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
    if req.work_dir:
        argv += ["--work-dir", str(Path(req.work_dir).resolve())]
    return argv


def activeRun() -> Optional[TaskState]:
    """The latest task iff it's still active (delegates to commands.isRunActive -- one policy)."""
    state = commands.resolveTargetTask()
    return state if commands.isRunActive(state) else None


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


def spawn(req: WorkRequest) -> int:
    """Spawn main.py as a DETACHED child (survives a bot restart). Returns the child PID."""
    config.LOG_PATH.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    logfile = open(config.LOG_PATH / f"work-{stamp}.log", "a", encoding="utf-8", errors="replace")
    creationflags = 0
    if os.name == "nt":
        creationflags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        buildArgv(req), cwd=str(config.PROJECT_ROOT),
        stdin=subprocess.DEVNULL, stdout=logfile, stderr=subprocess.STDOUT,
        close_fds=True, creationflags=creationflags,
    )
    logfile.close()  # child keeps its own duplicated handle; release the parent's copy
    LOG.info("Spawned /work run pid=%s mode=%s hours=%s", proc.pid, req.mode, req.hours)
    return proc.pid
