"""Safe self-modification gate -- lets 9to5 improve its OWN core loop without self-corruption.

When ``SELFMOD_ALLOW_CORE`` is on, a self-referential run may edit the core files
(orchestrator.py / main.py / config.py / agents/hooks.py). That is safe because:
  1. edits happen on the isolated ``sc/`` branch;
  2. the RUNNING Python process already imported the old modules, so its behavior for the
     rest of the run is unchanged (Python doesn't hot-reload);
  3. this gate runs AFTER the run finishes and, if core files changed, runs the test suite
     in a subprocess (fresh interpreter -> new code). If the tests fail, the core changes
     are REVERTED so a broken brain can never ship them.

The test runner is an injectable seam so the gate logic is offline-testable. Pure-stdlib.
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any, Callable, Optional

import config

LOG = config.getLogger("selfmod")


def _git(work_dir: str, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=work_dir, capture_output=True, text=True, timeout=30)


def core_files_changed(work_dir: str) -> list[str]:
    """Core protected files with uncommitted changes in ``work_dir`` (or [])."""
    try:
        r = _git(work_dir, "status", "--porcelain")
        if r.returncode != 0:
            return []
        changed = {line[3:].strip() for line in (r.stdout or "").splitlines() if line[3:].strip()}
        core = set(getattr(config, "CORE_PROTECTED_FILES", ()))
        return sorted(c for c in changed if c in core)
    except Exception as e:  # noqa: BLE001
        LOG.debug("core_files_changed failed (ignored): %s", e)
        return []


def _default_test_runner(work_dir: str) -> tuple[bool, str]:
    """Run the project test suite in a fresh interpreter; return (passed, tail-of-output)."""
    try:
        r = subprocess.run(["python", "-m", "unittest", "discover", "-s", "tests"],
                           cwd=work_dir, capture_output=True, text=True, timeout=1800)
        out = (r.stdout or "") + (r.stderr or "")
        return r.returncode == 0, out[-1500:]
    except Exception as e:  # noqa: BLE001
        return False, f"test runner error: {e}"


def revert_core(work_dir: str, files: list[str]) -> None:
    """Revert the given core files to HEAD (discard the breaking self-edit)."""
    if not files:
        return
    try:
        _git(work_dir, "checkout", "--", *files)
        LOG.warning("selfmod: reverted breaking core changes: %s", ", ".join(files))
    except Exception as e:  # noqa: BLE001
        LOG.error("selfmod revert failed: %s", e)


def safety_gate(work_dir: str, *, is_self_referential: bool,
                test_runner: Optional[Callable[[str], tuple[bool, str]]] = None) -> dict[str, Any]:
    """Run the post-run core-change safety gate. Returns a report dict.

    No-op unless self-ref + SELFMOD_ALLOW_CORE + core files actually changed. On a test
    failure it reverts the core changes so they can never reach a PR.
    """
    if not (is_self_referential and getattr(config, "SELFMOD_ALLOW_CORE", False)):
        return {"ran": False, "reason": "not_enabled"}
    changed = core_files_changed(work_dir)
    if not changed:
        return {"ran": False, "reason": "no_core_changes"}

    runner = test_runner or _default_test_runner
    LOG.info("selfmod safety gate: core files changed (%s) -> running test suite", changed)
    passed, output = runner(work_dir)
    if passed:
        LOG.info("selfmod safety gate PASSED -- core self-improvement is safe to ship")
        return {"ran": True, "passed": True, "changed": changed}
    revert_core(work_dir, changed)
    return {"ran": True, "passed": False, "changed": changed, "reverted": True,
            "output_tail": output[-500:]}
