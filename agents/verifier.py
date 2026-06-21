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
import shutil
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
    """Run a verify command string via the native shell (cmd.exe on Windows).

    Verifies are constrained to ``python <path>`` shapes, so the native shell is
    correct: cmd.exe handles Windows backslash paths AND nested quotes the way a
    human would type them. (bash would treat the backslashes in C:\\... as escapes
    and mangle the path.)
    """
    Path(work_dir).mkdir(parents=True, exist_ok=True)
    return subprocess.run(cmd, shell=True, capture_output=True, text=True, encoding="utf-8",
                          errors="replace", cwd=work_dir, timeout=config.VERIFY_TIMEOUT_SECONDS)


_VERIFY_STDLIB_OK = {
    "os", "sys", "json", "re", "pathlib", "subprocess", "math", "io", "time", "datetime",
    "collections", "itertools", "functools", "typing", "string", "random", "statistics",
    "textwrap", "shutil", "glob", "argparse", "csv", "hashlib", "base64", "unittest",
    "decimal", "fractions", "ast",
}


def sanitizeVerify(verify: Optional[dict]) -> Optional[dict]:
    """Drop a structurally-unreliable brain-authored verify so the subtask falls back to
    'executor exited 0' instead of failing forever on a bad check.

    Catches two failure modes: a malformed ``python -c`` one-liner (SyntaxError, e.g. a
    compound statement after ';'), AND a ``python -c`` that imports a non-stdlib / project
    module -- the 'guessed internal symbol' pattern (``from fibonacci import fib``) that
    fails even when the code under test is perfectly correct.
    """
    import ast
    if not isinstance(verify, dict):
        return None
    cmd = (verify.get("cmd") or "").strip()
    if not cmd:
        return None
    m = re.match(r"""(?:py|python|python3)\s+-c\s+(['"])(.*)\1\s*$""", cmd, re.DOTALL)
    if m:
        code = m.group(2)
        try:
            tree = ast.parse(code, "<verify>", "exec")
        except SyntaxError:
            LOG.info("sanitizeVerify: dropping malformed python -c verify: %s", cmd)
            return None
        for node in ast.walk(tree):
            mods: list[str] = []
            if isinstance(node, ast.Import):
                mods = [a.name.split(".")[0] for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                mods = [node.module.split(".")[0]]
            for mod in mods:
                if mod not in _VERIFY_STDLIB_OK:
                    LOG.info("sanitizeVerify: dropping verify importing non-stdlib '%s': %s", mod, cmd)
                    return None
    return verify


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
