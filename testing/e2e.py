"""End-to-end scenario runner: launch a FULL simulated run and drive it with a
VirtualOperator that acts as the human, then assert the outcome.

Run the built-in suite as a QA report:
    python -m testing.e2e

Each scenario starts a real ``runFull`` (wired with the --dry-run simulation doubles)
on a background thread, then a VirtualOperator performs scripted human actions through a
real control surface (web dashboard handler or the command spine) and we assert the
final run status. No Ollama / Claude / Discord / Obsidian is touched.
"""
from __future__ import annotations

import tempfile
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import config
import simulation
from state.task import TaskState
from testing.operator import VirtualOperator


@dataclass
class ScenarioResult:
    name: str
    ok: bool
    expected: str
    status: Optional[str]
    surface: str
    actions: list = field(default_factory=list)
    error: Optional[str] = None
    alive: bool = False
    elapsed: float = 0.0


# Config knobs that must be forced offline/fast for an E2E sim; saved + restored around a run.
_FORCED = {"WEB_DASHBOARD": False, "DISCORD_DASHBOARD": False,
           "CLAUDE_DOC_FETCH": False, "DISCORD_POLL_SECONDS": 0.02}


def runScenario(name: str, goal: str, script: Callable[[VirtualOperator], None], *,
                expect_status: str = "done", mode: str = "gated", n_subtasks: int = 2,
                surface: str = "web", timeout: float = 15.0) -> ScenarioResult:
    saved = {k: getattr(config, k) for k in _FORCED}
    for k, v in _FORCED.items():
        setattr(config, k, v)
    box: dict = {}
    t0 = time.time()
    try:
        state = TaskState.create(goal, 1.0)
        state.setElaboratedGoal(goal)
        state.save()
        orch = simulation.buildOrchestrator(n_subtasks=n_subtasks)
        work = tempfile.mkdtemp(prefix="9to5-e2e-")

        def _run() -> None:
            try:
                box["summary"] = orch.runFull(state, work_dir=work, auto_pr=False,
                                              control_mode=mode, parallelism=1)
            except Exception as e:  # noqa: BLE001
                box["error"] = repr(e)

        thread = threading.Thread(target=_run, name="e2e-run", daemon=True)
        thread.start()
        op = VirtualOperator(state.task_id, surface=surface, timeout=timeout)
        err = None
        try:
            script(op)
        except Exception as e:  # noqa: BLE001
            err = repr(e)
        thread.join(timeout=timeout)
        final = TaskState.loadSafe(state.task_id)
        status = final.meta.get("status") if final else None
        ok = (status == expect_status) and err is None and not thread.is_alive()
        return ScenarioResult(name, ok, expect_status, status, surface, list(op.actions),
                              err or box.get("error"), thread.is_alive(), round(time.time() - t0, 2))
    finally:
        for k, v in saved.items():
            setattr(config, k, v)


# --------------------------------------------------------------------------
# Built-in human scenarios -- each script reads like what a person would do.
# --------------------------------------------------------------------------
def _happy(op: VirtualOperator) -> None:
    op.approve("plan")        # human reviews the plan and approves
    op.approve("pre_pr")      # human approves the pre-PR safety gate


def _reject_plan(op: VirtualOperator) -> None:
    op.reject("plan")         # human rejects the plan -> run aborts


def _abort_at_gate(op: VirtualOperator) -> None:
    op.waitForGate("plan")
    op.abort()                # human pulls the plug at the plan gate


def _pause_resume_then_finish(op: VirtualOperator) -> None:
    op.waitForGate("plan")
    op.pause()
    op.resume()               # pause/resume must not disturb the gate
    op.approve("plan")
    op.approve("pre_pr")


def buildSuite() -> list:
    return [
        ("happy path (web surface)",
         lambda: runScenario("happy path (web surface)", "build a calculator app", _happy,
                             expect_status="done", surface="web")),
        ("happy path (command spine)",
         lambda: runScenario("happy path (command spine)", "build a calculator app", _happy,
                             expect_status="done", surface="bus")),
        ("operator rejects the plan",
         lambda: runScenario("operator rejects the plan", "build a thing", _reject_plan,
                             expect_status="aborted", surface="web")),
        ("operator aborts at the gate",
         lambda: runScenario("operator aborts at the gate", "build a thing", _abort_at_gate,
                             expect_status="aborted", surface="bus")),
        ("pause + resume then finish",
         lambda: runScenario("pause + resume then finish", "build a calculator app",
                             _pause_resume_then_finish, expect_status="done", surface="web")),
    ]


def runSuite() -> list:
    results = []
    for _name, runner in buildSuite():
        results.append(runner())
    return results


def main() -> int:
    print("\n  9TO5 — virtual-operator end-to-end test suite")
    print("  (full simulated runs driven by a scripted 'human'; no external services)\n  " + "=" * 62)
    results = runSuite()
    passed = 0
    for r in results:
        tag = "\033[92mPASS\033[0m" if r.ok else "\033[91mFAIL\033[0m"
        passed += 1 if r.ok else 0
        print(f"  [{tag}] {r.name:34s} status={r.status!s:9s} via {r.surface:4s} {r.elapsed:5.2f}s")
        if not r.ok:
            print(f"         expected={r.expected} got={r.status} alive={r.alive} error={r.error}")
            print(f"         human actions: {r.actions}")
    print("  " + "=" * 62)
    print(f"  {passed}/{len(results)} scenarios passed\n")
    return 0 if passed == len(results) else 1


if __name__ == "__main__":
    import sys
    sys.exit(main())
