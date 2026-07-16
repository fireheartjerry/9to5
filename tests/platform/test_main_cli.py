"""Tests for main CLI helper functions."""
from __future__ import annotations

from types import SimpleNamespace

import main
import orchestrator
from platform_core.cli import main_cli


def test_mention_shorthand_adds_goal_and_auto_approve():
    args = main_cli._applyMentionShorthand(["@9to5", "fix", "tests", "--hours", "2"])

    assert args == ["--goal", "fix tests", "--auto-approve", "--hours", "2"]


def test_main_cli_exposes_public_invocation_helpers_with_legacy_aliases():
    argv = main_cli.applyMentionShorthand(["@9to5", "fix", "tests"])
    assert argv == ["--goal", "fix tests", "--auto-approve"]
    assert main_cli.parseArgs(["--goal", "x"]).goal == "x"
    assert main_cli._applyMentionShorthand is main_cli.applyMentionShorthand
    assert main_cli._parseArgs is main_cli.parseArgs


def test_retry_failed_subtasks_resets_only_failed():
    class State:
        def __init__(self):
            self.subtasks = [
                {"subtask_id": "a", "status": "failed"},
                {"subtask_id": "b", "status": "done"},
            ]

        def updateSubtask(self, sid, **fields):
            next(s for s in self.subtasks if s["subtask_id"] == sid).update(fields)

    state = State()
    assert main_cli.retryFailedSubtasks(state) == 1
    assert state.subtasks[0]["status"] == "pending"
    assert state.subtasks[1]["status"] == "done"


def test_main_run_embargo_precedes_refresh_workdir_and_task_state(monkeypatch):
    import importlib
    guard = importlib.import_module("platform_core.execution.launch_guard")
    args = SimpleNamespace(health=False, e2e=False, dry_run=False, task_id=None, resume=None,
                           sim_run=False)
    monkeypatch.setattr(main, "_parseArgs", lambda argv: args)
    monkeypatch.setattr(main, "_applyConfigOverrides", lambda args: (_ for _ in ()).throw(
        AssertionError("config override reached")))
    monkeypatch.setattr(main, "refreshClaudeKnowledge", lambda: (_ for _ in ()).throw(
        AssertionError("knowledge refresh reached")))
    monkeypatch.setattr(main, "_resolveWorkDir", lambda args: (_ for _ in ()).throw(
        AssertionError("workdir reached")))
    with __import__("pytest").raises(guard.TransactionalKernelInactive):
        main.main()


def test_runfull_embargo_is_first_executable_boundary():
    import importlib
    guard = importlib.import_module("platform_core.execution.launch_guard")
    orch = object.__new__(orchestrator.Orchestrator)
    class PoisonState:
        @property
        def task_id(self):
            raise AssertionError("ControlBus/state reached")
    with __import__("pytest").raises(guard.TransactionalKernelInactive):
        orch.runFull(PoisonState(), work_dir="poison")


def test_resume_main_embargo_is_first_side_effect_after_parsing(monkeypatch):
    import importlib
    guard = importlib.import_module("platform_core.execution.launch_guard")
    args = SimpleNamespace(health=False, e2e=False, dry_run=False, task_id=None,
                           resume="a" * 32, sim_run=False)
    monkeypatch.setattr(main, "_parseArgs", lambda argv: args)
    monkeypatch.setattr(main, "_applyConfigOverrides", lambda args: (_ for _ in ()).throw(
        AssertionError("config reached")))
    monkeypatch.setattr(main, "_resumeRun", lambda args: (_ for _ in ()).throw(
        AssertionError("resume load reached")))
    with __import__("pytest").raises(guard.TransactionalKernelInactive):
        main.main()


def test_execute_run_uses_one_lifecycle_for_resume_and_forwards_resume(monkeypatch, capsys):
    from platform_core.runtime import resilience, run_lifecycle

    state = SimpleNamespace(task_id="task-1", meta={})
    args = SimpleNamespace(no_pr=True, mode="watch", parallel=0)
    active: list[str] = []
    captured: dict = {}

    class Orchestrator:
        def runFull(self, run_state, **kwargs):
            captured["state"] = run_state
            captured.update(kwargs)
            return {"status": "done"}

    monkeypatch.setattr(main.sys, "stdin", SimpleNamespace(isatty=lambda: False))
    monkeypatch.setattr(run_lifecycle, "markRunActive", lambda st: active.append(st.task_id))
    monkeypatch.setattr(main, "_buildRunOrchestrator", lambda _args: Orchestrator())
    monkeypatch.setattr(resilience, "run_with_recovery", lambda runner, st: runner(st))

    assert main._executeRun(args, state, "C:/repo", resume=True) == 0
    assert active == ["task-1"]
    assert captured["state"] is state
    assert captured["work_dir"] == "C:/repo"
    assert captured["auto_pr"] is False
    assert captured["control_mode"] == "watch"
    assert captured["parallelism"] == 1
    assert captured["resume"] is True
    assert "RUN SUMMARY" in capsys.readouterr().out
