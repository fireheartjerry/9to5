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
from pathlib import Path
from typing import Callable, Optional

import config
import platform_core.simulator.simulation as simulation
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
    summary: dict = field(default_factory=dict)


# Config knobs forced offline/fast for an E2E sim; saved + restored around a run.
# CRITICAL: blank the Discord CREDENTIALS, not just DISCORD_DASHBOARD. Milestone embeds
# (architect_done / plan_ready / pre_pr approval / notices) gate on DISCORD_BOT_TOKEN +
# DISCORD_CHANNEL_ID inside discord_bot._request -- NOT on DISCORD_DASHBOARD -- so without this a
# sim run posts REAL embeds to the live channel under ANY runner (conftest's mute is pytest-only;
# `unittest discover` bypasses it). Mirrors conftest._no_real_discord so the harness is hermetic.
_FORCED = {"WEB_DASHBOARD": False, "DISCORD_DASHBOARD": False,
           "CLAUDE_DOC_FETCH": False, "DISCORD_POLL_SECONDS": 0.02,
           "DISCORD_BOT_TOKEN": "", "DISCORD_CHANNEL_ID": 0,
           # The virtual operator IS a human at the controls: night mode (which a
           # production .env may enable) would auto-resume pauses and drop the PR hold,
           # breaking the very interactions these scenarios script.
           "NIGHT_MODE": False,
           # Hermetic like conftest: a production .env (loaded from INSTALL_ROOT by ANY
           # runner, pytest or not) must not let a scenario probe the REAL Gemini API
           # (observed: live 429 quota burn per scenario) or the browser layer.
           "GEMINI_ENABLED": False, "BROWSER_LAYER_ENABLED": False,
           # Scenarios must run the same planner CI's default config runs: the dual-ledger
           # path adds depends_on chains that change skip/add gate semantics mid-scenario.
           "DUAL_LEDGER_PLANNER_ENABLED": False}


def _isolateState() -> dict:
    """Point the state/control/heartbeat tree at a scenario-scoped temp dir (mirrors
    tests/conftest._isolate_state -- this harness runs OUTSIDE pytest, so without it every
    scenario wrote task files into the REAL state/tasks, and the self-modification guard's
    loadLatest() fallback then enforced a finished e2e scenario's universe on the next
    interactive session). Returns the {attr: saved_value} map for restore."""
    from platform_core.runtime import control_store
    base = Path(tempfile.mkdtemp(prefix="9to5-e2e-state-"))
    saved = {}
    for attr, sub in (("STATE_DIR", "state_tasks"), ("CONTROL_DIR", "state_control"),
                      ("HEARTBEAT_DIR", "state_heartbeats"), ("LAUNCH_DIR", "state_launch"),
                      ("IPC_DIR", "state_ipc")):
        saved[attr] = getattr(config, attr)
        d = base / sub
        d.mkdir(parents=True, exist_ok=True)
        setattr(config, attr, d)
    saved["_DB_OVERRIDE"] = getattr(control_store, "_DB_OVERRIDE", None)
    control_store._DB_OVERRIDE = base / "control.db"
    return saved


def _restoreState(saved: dict) -> None:
    from platform_core.runtime import control_store
    control_store._DB_OVERRIDE = saved.pop("_DB_OVERRIDE", None)
    for attr, val in saved.items():
        setattr(config, attr, val)


def runScenario(name: str, goal: str, script: Callable[[VirtualOperator], None], *,
                expect_status: str = "done", mode: str = "gated", n_subtasks: int = 2,
                surface: str = "web", timeout: float = 15.0, review=None,
                auto_pr: bool = False) -> ScenarioResult:
    saved = {k: getattr(config, k) for k in _FORCED}
    for k, v in _FORCED.items():
        setattr(config, k, v)
    saved_state = _isolateState()
    # WEB_DASHBOARD / CLAUDE_DOC_FETCH are run-scoped flags (R12): platform_core readers
    # (e.g. knowledge_refresh) resolve them via settings.runFlags(), which a shadow on the
    # root config module does not reach -- force + restore the flag object too.
    from platform_core.app_config import settings as _app_settings
    flags = _app_settings.runFlags()
    saved_flags = {"WEB_DASHBOARD": flags.WEB_DASHBOARD, "CLAUDE_DOC_FETCH": flags.CLAUDE_DOC_FETCH,
                   "NIGHT_MODE": flags.NIGHT_MODE}
    flags.WEB_DASHBOARD = False
    flags.CLAUDE_DOC_FETCH = False
    flags.NIGHT_MODE = False
    box: dict = {}
    t0 = time.time()
    try:
        state = TaskState.create(goal, 1.0)
        state.setElaboratedGoal(goal)
        state.save()
        orch = simulation.buildOrchestrator(n_subtasks=n_subtasks)
        if review is not None:
            orch._review = review   # inject a custom adversary verdict (e.g. to test PR-hold)
        work = tempfile.mkdtemp(prefix="9to5-e2e-")

        def _run() -> None:
            try:
                box["summary"] = orch.runFull(state, work_dir=work, auto_pr=auto_pr,
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
                              err or box.get("error"), thread.is_alive(), round(time.time() - t0, 2),
                              box.get("summary") or {})
    finally:
        _restoreState(saved_state)
        for k, v in saved.items():
            setattr(config, k, v)
        for k, v in saved_flags.items():
            setattr(flags, k, v)


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


def _skip_at_gate(op: VirtualOperator) -> None:
    op.waitForGate("plan")
    op.skip("st-002")         # human drops a subtask at the plan gate (applied live in the gate loop)
    op.approve("plan")
    op.approve("pre_pr")


def _add_at_gate(op: VirtualOperator) -> None:
    op.waitForGate("plan")
    op.add("an extra subtask the human wants")
    op.approve("plan")
    op.approve("pre_pr")


def _challengedReview(subtask_title, trigger_reason, executor_output, *, ollama_chat=None, goal=""):
    return {"verdict": "challenged", "trigger_reason": trigger_reason,
            "concerns": ["no rollback path"], "notes": "", "stub": False}


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
        ("skip a subtask at the gate",
         lambda: runScenario("skip a subtask at the gate", "build (1) add (2) sub (3) mul",
                             _skip_at_gate, expect_status="done", surface="web", n_subtasks=3)),
        ("add a subtask at the gate",
         lambda: runScenario("add a subtask at the gate", "build (1) add (2) sub (3) mul",
                             _add_at_gate, expect_status="done", surface="bus", n_subtasks=3)),
        ("adversary holds the PR",
         lambda: runScenario("adversary holds the PR", "build a calculator app", _happy,
                             expect_status="done", surface="web", review=_challengedReview,
                             auto_pr=True)),
    ]


def runSuite() -> list:
    # Pre-warm the one-time per-process work (offline capabilities build) OUTSIDE any
    # scenario, so scenario 1 doesn't spend most of its 15s operator budget on it on a
    # cold runner. Best-effort: a failure here surfaces in the scenario itself.
    try:
        import knowledge
        knowledge.ensureCapabilities()
    except Exception:  # noqa: BLE001
        pass
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
