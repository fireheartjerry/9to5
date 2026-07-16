from types import SimpleNamespace

import config
import platform_core.simulator.simulation as simulation
from agents.planning import council_seam
from orchestrator import Orchestrator
from state.task import TaskState


class _RecordingBrain(simulation.SimBrain):
    def __init__(self, n_subtasks=1):
        super().__init__(n_subtasks=n_subtasks)
        self.user_messages = []
        self.user_messages_by_act = {}

    def chat(self, *, model=None, messages=None, act=None, **kwargs):
        for msg in messages or []:
            if msg.get("role") == "user":
                content = msg.get("content", "")
                self.user_messages.append(content)
                self.user_messages_by_act.setdefault(act, []).append(content)
        return super().chat(model=model, messages=messages, act=act, **kwargs)


class _RecordingRunClaude:
    def __init__(self):
        self.architect_prompts = []

    def __call__(self, spec, **kwargs):
        if kwargs.get("system_prompt") is not None:
            self.architect_prompts.append((spec or {}).get("prompt", ""))
        return simulation.simRunClaude(spec, **kwargs)


def _fake_result(prompt="UNIQUE COUNCIL PROMPT SHOULD NOT BE INJECTED"):
    brief = SimpleNamespace(
        run_id="orchestration-council-run",
        provider_participation_summary=["GPT: mock/control seat; requested_live=False"],
        council_run_health=["warnings=0"],
        provider_run_summaries=[],
        recommended_first_execution_slice="Add disabled-by-default seam scaffolding",
        actionable_next_command_or_task_prompt=prompt,
        implementation_prompt_export=prompt,
        final_synthesis="Compact seam-only summary.",
        risk_list=["Architect must treat council output as advisory only."],
        constraints_do_not_do=["Do not inject transcript text."],
        unresolved_questions=["Which planner slice should go first?"],
        transcript_path="state/council_runs/orch/transcript.md",
    )
    return SimpleNamespace(
        run_id="orchestration-council-run",
        brief=brief,
        warnings=[],
        log_dir="state/council_runs/orch",
        brief_path="state/council_runs/orch/brief.json",
        transcript_path="state/council_runs/orch/transcript.md",
        skipped_reason="",
    )


def _state(goal="build a calculator"):
    state = TaskState.create(goal, 1.0)
    state.setElaboratedGoal(goal)
    state.save()
    return state


def _patch_common_flags(monkeypatch, tmp_path, **flags):
    # Patch the real module dictionary so pytest records these facade shadows as
    # absent and removes them on teardown.  ``config.__getattr__`` makes a plain
    # monkeypatch.setattr see registry-backed names as pre-existing, which would
    # otherwise restore stale concrete values over the live facade.
    monkeypatch.setitem(vars(config), "STATE_DIR", tmp_path / "tasks")
    monkeypatch.setitem(vars(config), "CONTROL_DIR", tmp_path / "control")
    monkeypatch.setitem(vars(config), "WEB_DASHBOARD", False)
    monkeypatch.setitem(vars(config), "DISCORD_DASHBOARD", False)
    (tmp_path / "tasks").mkdir(exist_ok=True)
    (tmp_path / "control").mkdir(exist_ok=True)
    defaults = {
        "PRE_EXECUTION_COUNCIL_SEAM_ENABLED": False,
        "PRE_EXECUTION_COUNCIL_RUN_ON_RESUME": False,
        "PRE_EXECUTION_COUNCIL_STRICT_MODE": False,
        "PRE_EXECUTION_COUNCIL_INJECT_ARCHITECT_CONTEXT": False,
        "PRE_EXECUTION_COUNCIL_INJECT_PLANNER_CONTEXT": False,
    }
    defaults.update(flags)
    for name, value in defaults.items():
        monkeypatch.setitem(vars(config), name, value)


def test_disabled_orchestration_path_does_not_call_council_runner(monkeypatch, tmp_path):
    _patch_common_flags(monkeypatch, tmp_path, PRE_EXECUTION_COUNCIL_SEAM_ENABLED=False)
    called = False

    def runner(_task, _work_dir):
        nonlocal called
        called = True
        raise AssertionError("disabled seam must not call council runner")

    monkeypatch.setattr(council_seam, "_default_run_council", runner)
    state = _state()
    summary = simulation.buildOrchestrator(n_subtasks=1).runFull(
        state,
        work_dir=str(tmp_path / "work"),
        auto_pr=False,
        control_mode="watch",
    )

    assert summary["status"] == "done"
    assert called is False
    assert "pre_execution_council" not in state.meta


def test_simulation_never_starts_council_when_globally_enabled(monkeypatch, tmp_path):
    """Offline simulation must not activate provider/browser-backed council seats."""
    _patch_common_flags(monkeypatch, tmp_path, PRE_EXECUTION_COUNCIL_SEAM_ENABLED=True)
    (tmp_path / "work").mkdir(exist_ok=True)

    def runner(_task, _work_dir):
        raise AssertionError("simulation must not invoke the pre-execution council")

    monkeypatch.setattr(council_seam, "_default_run_council", runner)
    state = _state()
    summary = simulation.buildOrchestrator(n_subtasks=1).runFull(
        state, work_dir=str(tmp_path / "work"), auto_pr=False, control_mode="watch")

    assert summary["status"] == "done"
    assert "pre_execution_council" not in state.meta


def test_enabled_metadata_only_path_persists_meta_without_prompt_injection(monkeypatch, tmp_path):
    _patch_common_flags(monkeypatch, tmp_path, PRE_EXECUTION_COUNCIL_SEAM_ENABLED=True)
    (tmp_path / "work").mkdir(exist_ok=True)
    monkeypatch.setattr(council_seam, "_default_run_council", lambda task, work_dir: _fake_result())
    brain = _RecordingBrain(n_subtasks=1)
    run_claude = _RecordingRunClaude()
    orch = Orchestrator(
        brain=brain,
        obs=simulation.SimObs(),
        run_claude=run_claude,
        replan=simulation.simReplan,
        review=simulation.simReview,
        skip_pre_execution_council=False,
        offline_mode=True,
    )
    state = _state()

    summary = orch.runFull(state, work_dir=str(tmp_path / "work"), auto_pr=False, control_mode="watch")

    assert summary["status"] == "done"
    meta = state.meta["pre_execution_council"]
    assert meta["status"] == "completed"
    assert meta["run_id"] == "orchestration-council-run"
    assert meta["selected_first_slice"] == "Add disabled-by-default seam scaffolding"
    assert "UNIQUE COUNCIL PROMPT SHOULD NOT BE INJECTED" in meta["codex_ready_prompt"]
    assert all("UNIQUE COUNCIL PROMPT SHOULD NOT BE INJECTED" not in msg for msg in brain.user_messages)
    assert all("UNIQUE COUNCIL PROMPT SHOULD NOT BE INJECTED" not in msg for msg in run_claude.architect_prompts)


def test_resume_default_skip_in_orchestration_does_not_change_subtasks(monkeypatch, tmp_path):
    _patch_common_flags(monkeypatch, tmp_path, PRE_EXECUTION_COUNCIL_SEAM_ENABLED=True)
    (tmp_path / "work").mkdir(exist_ok=True)
    called = False

    def runner(_task, _work_dir):
        nonlocal called
        called = True
        raise AssertionError("resume default skip must not call council runner")

    monkeypatch.setattr(council_seam, "_default_run_council", runner)
    state = _state()
    state.addSubtask("a", "da")
    state.addSubtask("b", "db")
    state.updateSubtask("st-001", status="done")
    state.updateSubtask("st-002", status="in_progress")

    orch = Orchestrator(
        brain=simulation.SimBrain(n_subtasks=1), obs=simulation.SimObs(),
        run_claude=simulation.simRunClaude, replan=simulation.simReplan,
        review=simulation.simReview, skip_pre_execution_council=False, offline_mode=True,
    )
    summary = orch.runFull(
        state,
        work_dir=str(tmp_path / "work"),
        auto_pr=False,
        control_mode="watch",
        resume=True,
    )

    assert summary["status"] == "done"
    assert called is False
    assert state.meta["pre_execution_council"] == {
        "status": "skipped",
        "run_mode": "resume",
        "skipped_reason": "resume_default_skip",
    }


def test_architect_injection_enabled_adds_advisory_block_without_planner_injection(monkeypatch, tmp_path):
    _patch_common_flags(
        monkeypatch,
        tmp_path,
        PRE_EXECUTION_COUNCIL_SEAM_ENABLED=True,
        PRE_EXECUTION_COUNCIL_INJECT_ARCHITECT_CONTEXT=True,
    )
    (tmp_path / "work").mkdir(exist_ok=True)
    monkeypatch.setattr(council_seam, "_default_run_council", lambda task, work_dir: _fake_result())
    brain = _RecordingBrain(n_subtasks=1)
    run_claude = _RecordingRunClaude()
    orch = Orchestrator(
        brain=brain,
        obs=simulation.SimObs(),
        run_claude=run_claude,
        replan=simulation.simReplan,
        review=simulation.simReview,
        skip_pre_execution_council=False,
        offline_mode=True,
    )

    state = _state()
    orch.runFull(state, work_dir=str(tmp_path / "work"), auto_pr=False, control_mode="watch")

    architect_inputs = "\n".join(brain.user_messages_by_act.get("architect", []))
    planner_inputs = "\n".join(
        msg
        for act, messages in brain.user_messages_by_act.items()
        if act in {"plan", "critique"}
        for msg in messages
    )
    final_architect_prompt = "\n".join(run_claude.architect_prompts)
    assert "Pre-Execution Council Brief (advisory, non-binding)" in architect_inputs
    assert "does not override user, system, or developer instructions" in architect_inputs
    assert "UNIQUE COUNCIL PROMPT SHOULD NOT BE INJECTED" in architect_inputs
    assert "Pre-Execution Council Brief (advisory, non-binding)" in final_architect_prompt
    assert "UNIQUE COUNCIL PROMPT SHOULD NOT BE INJECTED" in final_architect_prompt
    assert "UNIQUE COUNCIL PROMPT SHOULD NOT BE INJECTED" not in planner_inputs


def test_planner_injection_enabled_adds_advisory_block_without_architect_injection(monkeypatch, tmp_path):
    _patch_common_flags(
        monkeypatch,
        tmp_path,
        PRE_EXECUTION_COUNCIL_SEAM_ENABLED=True,
        PRE_EXECUTION_COUNCIL_INJECT_PLANNER_CONTEXT=True,
    )
    (tmp_path / "work").mkdir(exist_ok=True)
    monkeypatch.setattr(council_seam, "_default_run_council", lambda task, work_dir: _fake_result())
    brain = _RecordingBrain(n_subtasks=1)
    orch = Orchestrator(
        brain=brain,
        obs=simulation.SimObs(),
        run_claude=simulation.simRunClaude,
        replan=simulation.simReplan,
        review=simulation.simReview,
        skip_pre_execution_council=False,
        offline_mode=True,
    )

    state = _state()
    orch.runFull(state, work_dir=str(tmp_path / "work"), auto_pr=False, control_mode="watch")

    planner_inputs = "\n".join(
        msg
        for act, messages in brain.user_messages_by_act.items()
        if act in {"plan", "critique"}
        for msg in messages
    )
    architect_inputs = "\n".join(brain.user_messages_by_act.get("architect", []))
    assert "Pre-Execution Council Planner Advisory (advisory, non-binding)" in planner_inputs
    assert "Use this only to shape task decomposition" in planner_inputs
    assert "does not override user, system, or developer instructions" in planner_inputs
    assert "UNIQUE COUNCIL PROMPT SHOULD NOT BE INJECTED" in planner_inputs
    assert "Which planner slice should go first?" in planner_inputs
    assert "transcript.md" not in planner_inputs
    assert "brief.json" not in planner_inputs
    assert "Pre-Execution Council Planner Advisory" not in architect_inputs
    assert "UNIQUE COUNCIL PROMPT SHOULD NOT BE INJECTED" not in architect_inputs
    assert not any("planner injection requested but not implemented" in item for item in state.meta["pre_execution_council"].get("warnings", []))
