"""Verifier -- run the brain-authored verification check for a subtask.

Each subtask carries a ``verify`` block authored by the Orchestrator brain:

    {"cmd": "python -m taskcli --help", "expect": "exit_zero"}

``expect`` is one of:
  * ``exit_zero``                -- the command returned exit code 0
  * ``stdout_contains:<text>``   -- <text> appears in stdout
  * ``stdout_regex:<pattern>``   -- <pattern> matches stdout (re.search)

If ``cmd`` is null/empty the gate falls back to "the executor process exited 0".
The command is run deterministically in the subtask's working directory; this
module never asks the model anything -- it only executes and compares.
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Optional

import config

LOG = config.getLogger("verifier")

_MAX_CAP = 2000  # truncate captured output


def _cap(text: Optional[str]) -> str:
    text = text or ""
    return text if len(text) <= _MAX_CAP else text[:_MAX_CAP] + "\n...[truncated]"


def _runShell(cmd: str, work_dir: str) -> subprocess.CompletedProcess:
    """Run a shell command string in work_dir.

    ``shell=True`` with the raw string lets the platform shell (cmd.exe on
    Windows, /bin/sh elsewhere) parse quoting exactly as a human would at a
    prompt -- avoiding ``list2cmdline`` re-quoting of nested quotes.
    """
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    return subprocess.run(
        cmd,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        cwd=work_dir,
        timeout=config.VERIFY_TIMEOUT_SECONDS,
    )


def _evaluate(expect: str, returncode: int, stdout: str) -> bool:
    expect = (expect or config.VERIFY_DEFAULT_EXPECT).strip()
    if expect == "exit_zero":
        return returncode == 0
    if expect.startswith("stdout_contains:"):
        needle = expect[len("stdout_contains:"):]
        return needle in stdout
    if expect.startswith("stdout_regex:"):
        pattern = expect[len("stdout_regex:"):]
        try:
            return re.search(pattern, stdout) is not None
        except re.error:
            return False
    # Unknown expectation -> conservative default.
    return returncode == 0


def runVerification(verify: Optional[dict], work_dir: str, executor_result: dict) -> dict:
    """Return a verify_result dict: {passed, cmd, expect, returncode, stdout, stderr}."""
    cmd = (verify or {}).get("cmd") if verify else None
    expect = (verify or {}).get("expect") or config.VERIFY_DEFAULT_EXPECT

    # No command authored -> trust the executor's own exit status.
    if not cmd:
        passed = bool(executor_result.get("ok"))
        return {
            "passed": passed,
            "cmd": None,
            "expect": "executor_exit_zero",
            "returncode": executor_result.get("returncode"),
            "stdout": "",
            "stderr": "" if passed else _cap(executor_result.get("stderr")),
        }

    LOG.info("Verifying: %s  (expect: %s)", cmd, expect)
    try:
        proc = _runShell(cmd, work_dir)
        passed = _evaluate(expect, proc.returncode, proc.stdout or "")
        result = {
            "passed": passed,
            "cmd": cmd,
            "expect": expect,
            "returncode": proc.returncode,
            "stdout": _cap(proc.stdout),
            "stderr": _cap(proc.stderr),
        }
    except subprocess.TimeoutExpired:
        result = {"passed": False, "cmd": cmd, "expect": expect, "returncode": -1,
                  "stdout": "", "stderr": f"verify TIMEOUT after {config.VERIFY_TIMEOUT_SECONDS}s"}
    except Exception as e:  # noqa: BLE001
        result = {"passed": False, "cmd": cmd, "expect": expect, "returncode": -1,
                  "stdout": "", "stderr": f"verify error: {e}"}
    LOG.info("Verify %s -> %s (rc=%s)", "PASS" if result["passed"] else "FAIL", cmd, result["returncode"])
    return result
