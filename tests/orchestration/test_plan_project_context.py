"""Task 9 (any-project capabilities, spec §3.4): flag-gated, fail-open project-context
injection into plan authoring.

Covers: (a) flag on + real tiny project => plan user prompt carries a PROJECT CONTEXT
section; (b) flag on + broken scanner => planning still returns, no section (fail-open);
(c) flag off => no injection AND extractProject is never called; plus knob reachability
through the ``config`` facade."""
from unittest import mock

import config
from orchestrator import Orchestrator

_PLAN_JSON = (
    '{"subtasks": [{"title": "a", "description": "d", '
    '"verify": {"cmd": "python a.py", "expect": "exit_zero"}}]}'
)


def _makeOrch():
    """Orchestrator with every external seam injected (no Ollama / Claude CLI / Obsidian)."""
    return Orchestrator(brain=mock.Mock(), obs=mock.Mock(), run_claude=mock.Mock(),
                        replan=mock.Mock(), review=mock.Mock())


def _stubBrain(orch) -> list:
    """Replace _ollamaChat with a prompt-capturing stub returning a valid plan JSON."""
    captured: list[str] = []

    def _chat(system, user, **kw):
        captured.append(user)
        return {"message": {"content": _PLAN_JSON}}

    orch._ollamaChat = _chat
    return captured


def _tinyProject(tmp_path):
    (tmp_path / "app.py").write_text("import helper\n\nprint(helper.VALUE)\n", encoding="utf-8")
    (tmp_path / "helper.py").write_text("VALUE = 1\n", encoding="utf-8")
    return tmp_path


def test_plan_prompt_includes_project_context(pin_flags, tmp_path):
    pin_flags(PROJECT_INTROSPECTION_ENABLED=True, DUAL_LEDGER_PLANNER_ENABLED=False)
    work_dir = _tinyProject(tmp_path)
    orch = _makeOrch()
    orch._work_dir = str(work_dir)  # same source execution uses (runExecutionLoop sets it)
    captured = _stubBrain(orch)
    subs = orch.authorSubtaskPlan("build the thing", "arch doc")
    assert subs and subs[0]["title"] == "a"
    assert captured and "PROJECT CONTEXT" in captured[0]


def test_plan_prompt_fail_open_on_scan_error(pin_flags, monkeypatch, tmp_path):
    pin_flags(PROJECT_INTROSPECTION_ENABLED=True, DUAL_LEDGER_PLANNER_ENABLED=False)

    def _boom(*a, **k):
        raise RuntimeError("scan exploded")

    monkeypatch.setattr("developer_tools.introspection.project_extract.extractProject", _boom)
    orch = _makeOrch()
    orch._work_dir = str(tmp_path)
    captured = _stubBrain(orch)
    subs = orch.authorSubtaskPlan("build the thing", "arch doc")
    assert subs and subs[0]["title"] == "a"  # planning still returns a usable plan
    assert captured and "PROJECT CONTEXT" not in captured[0]


def test_flag_off_no_injection_and_no_scan(pin_flags, monkeypatch, tmp_path):
    pin_flags(PROJECT_INTROSPECTION_ENABLED=False, DUAL_LEDGER_PLANNER_ENABLED=False)
    spy = mock.Mock()
    monkeypatch.setattr("developer_tools.introspection.project_extract.extractProject", spy)
    orch = _makeOrch()
    orch._work_dir = str(_tinyProject(tmp_path))
    captured = _stubBrain(orch)
    subs = orch.authorSubtaskPlan("build the thing", "arch doc")
    assert subs and subs[0]["title"] == "a"
    assert captured and "PROJECT CONTEXT" not in captured[0]
    assert spy.call_count == 0


def test_plan_context_hard_time_budget(pin_flags, monkeypatch, tmp_path):
    """A pathologically slow extraction must cost at most the budget, then fail open to ''."""
    import threading
    import platform_core.orchestration.plan_context as pc

    pin_flags(PROJECT_INTROSPECTION_ENABLED=True, DUAL_LEDGER_PLANNER_ENABLED=False)
    release = threading.Event()

    def _slowExtract(*a, **k):
        release.wait(5)  # blocks past the (shrunk) budget; conftest only caps time.sleep
        raise RuntimeError("never reached in time")

    monkeypatch.setattr("developer_tools.introspection.project_extract.extractProject", _slowExtract)
    monkeypatch.setattr(pc, "PROJECT_CONTEXT_TIMEOUT_S", 0.2)
    orch = _makeOrch()
    orch._work_dir = str(tmp_path)
    captured = _stubBrain(orch)
    subs = orch.authorSubtaskPlan("build the thing", "arch doc")
    release.set()  # let the stranded worker thread exit promptly
    assert subs and subs[0]["title"] == "a"
    assert captured and "PROJECT CONTEXT" not in captured[0]


def test_dual_ledger_path_receives_project_context(pin_flags, monkeypatch, tmp_path):
    """Default full-stack config routes planning through the dual-ledger planner; the
    project context must reach it too (own param, own budget -- not lost to truncation)."""
    pin_flags(PROJECT_INTROSPECTION_ENABLED=True, DUAL_LEDGER_PLANNER_ENABLED=True)
    seen: dict = {}

    def _fakeTryAuthorPlan(chat, goal, architect_doc, work_profile=None, project_ctx=""):
        seen["project_ctx"] = project_ctx
        return [{"title": "a", "description": "d"}]

    monkeypatch.setattr("platform_core.orchestration.plan_mixin._dlp.tryAuthorPlan",
                        _fakeTryAuthorPlan)
    orch = _makeOrch()
    orch._work_dir = str(_tinyProject(tmp_path))
    _stubBrain(orch)
    subs = orch.authorSubtaskPlan("build the thing", "arch doc")
    assert subs and subs[0]["title"] == "a"
    assert "PROJECT CONTEXT" in seen.get("project_ctx", "")


def test_knobs_reachable_via_config_facade():
    assert isinstance(config.PROJECT_INTROSPECTION_ENABLED, bool)
    assert isinstance(config.PROJECT_INTROSPECTION_MAX_FILES, int)
    assert config.PROJECT_INTROSPECTION_MAX_FILES >= 1
    assert isinstance(config.EXPLORE_APPROACHES_ENABLED, bool)
    assert isinstance(config.EXPLORE_APPROACHES_N, int)
    assert config.EXPLORE_APPROACHES_N >= 1
