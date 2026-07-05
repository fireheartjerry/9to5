"""Planner-authored ``files_touched`` must survive from a brain-authored plan dict into the
real subtask record at every creation site -- otherwise Epic 1's parallel-safety disjoint
scheduling (parallel_safety.filesTouched) and Epic 5's selectDisjointBatch seam always see an
empty set and silently serialize everything to one-at-a-time, no matter what the planner
authored. Found via the combined-epic-flags integration test (tests/test_epic_flags_combined.py)."""

from datetime import datetime, timedelta

import config
from platform_core.orchestration import dual_ledger_planner as dlp
from platform_core.orchestration.run_loop_mixin import OrchestratorRunLoopMixin
from platform_core.orchestration.run_phase_mixin import OrchestratorRunPhaseMixin
from state.task import TaskState


class _PhaseStub(OrchestratorRunPhaseMixin):
    pass


def test_persist_plan_subtasks_forwards_files_touched(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(config, "DUAL_LEDGER_PLANNER_ENABLED", False, raising=False)
    state = TaskState.create("goal", 1.0)
    s = _PhaseStub()
    s._persistPlanSubtasks(
        state,
        [
            {
                "title": "build a",
                "description": "make a.py",
                "layer": 3,
                "verify": None,
                "files_touched": ["a.py"],
            },
        ],
    )
    assert state.subtasks[0]["files_touched"] == ["a.py"]


def test_persist_plan_subtasks_warns_and_notifies_when_over_cap(monkeypatch, tmp_path, caplog):
    """REGRESSION: over-cap plans are truncated to MAX_SUBTASKS at commit time; that drop used to
    be SILENT (the replan path logs its skip). It must now log + add a run notification, without
    changing the cap semantics."""
    import logging

    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(config, "DUAL_LEDGER_PLANNER_ENABLED", False, raising=False)
    monkeypatch.setattr(config, "MAX_SUBTASKS", 2, raising=False)
    state = TaskState.create("goal", 1.0)
    plan = [{"title": f"d{i}", "description": "", "layer": 3, "verify": None} for i in range(5)]
    with caplog.at_level(logging.WARNING):
        _PhaseStub()._persistPlanSubtasks(state, plan)
    assert len(state.subtasks) == 2  # cap semantics unchanged
    assert any("MAX_SUBTASKS" in r.message for r in caplog.records), "over-cap drop was not logged"
    assert any(n.get("kind") == "plan_truncated" for n in state.data.get("notifications", [])), (
        "over-cap drop was not surfaced as a notification"
    )


def test_persist_plan_under_cap_is_silent(monkeypatch, tmp_path, caplog):
    """A plan within the cap must NOT log a truncation warning or add a notification."""
    import logging

    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(config, "DUAL_LEDGER_PLANNER_ENABLED", False, raising=False)
    monkeypatch.setattr(config, "MAX_SUBTASKS", 8, raising=False)
    state = TaskState.create("goal", 1.0)
    with caplog.at_level(logging.WARNING):
        _PhaseStub()._persistPlanSubtasks(state, [{"title": "only", "description": "", "verify": None}])
    assert not any("MAX_SUBTASKS" in r.message for r in caplog.records)
    assert not any(n.get("kind") == "plan_truncated" for n in state.data.get("notifications", []))


def test_materialize_dag_forwards_files_touched(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    state = TaskState.create("goal", 1.0)
    created = dlp.materializeDag(
        state,
        [
            {
                "title": "build a",
                "description": "make a.py",
                "layer": 3,
                "verify": None,
                "files_touched": ["a.py"],
            },
        ],
    )
    assert created[0]["files_touched"] == ["a.py"]
    assert state.getSubtask(created[0]["subtask_id"])["files_touched"] == ["a.py"]


class _LoopStub(OrchestratorRunLoopMixin):
    pass


class _FakeDashboard:
    def update(self, *a, **k):
        pass

    def event(self, *a, **k):
        pass


def test_backfill_horizon_fill_forwards_files_touched(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    state = TaskState.create("goal", 1.0)
    state.meta["deadline_at"] = (datetime.now().astimezone() + timedelta(hours=1)).isoformat()
    s = _LoopStub()
    s._state_lock = __import__("threading").Lock()
    s.authorBackfillBatch = lambda *a, **k: [
        {
            "title": "improve x",
            "description": "edit x.py",
            "layer": 3,
            "verify": None,
            "files_touched": ["x.py"],
        }
    ]
    s._strengthenPlanVerifies = lambda goal, batch: batch
    s.writeIndex = lambda *_a, **_k: None
    added = s._backfill(state, "architect doc", _FakeDashboard())
    assert added == 1
    assert state.subtasks[0]["files_touched"] == ["x.py"]


class _FakeObs:
    def appendNote(self, *a, **k):
        pass


def test_apply_replan_add_forwards_files_touched(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    state = TaskState.create("goal", 1.0)
    s = _LoopStub()
    s.obs = _FakeObs()
    decision = {
        "action": "mutate",
        "add": [
            {
                "title": "new work",
                "description": "edit y.py",
                "layer": 3,
                "verify": None,
                "files_touched": ["y.py"],
            }
        ],
        "remove": [],
    }
    s._applyReplan(state, decision)
    assert state.subtasks[0]["files_touched"] == ["y.py"]
