from platform_core.orchestration import clarification_replan, dual_ledger_replan
from platform_core.orchestration.execute_mixin import OrchestratorExecuteMixin
from platform_core.orchestration.run_loop_mixin import OrchestratorRunLoopMixin
from state.task import TaskState


def _blocked_result():
    return {
        "subtype": "blocked_clarification",
        "clarification": {
            "records": [{
                "decision_id": "migration_destructive_allowed",
                "question_text": "Can this migration drop existing rows?",
                "risk": "high",
                "options": ["No destructive changes", "Allowed with backup"],
            }]
        },
    }


def test_blocked_clarification_decision_creates_readonly_probe():
    decision = clarification_replan.blockedClarificationDecision(
        {"title": "Implement migration", "layer": 3}, _blocked_result())
    assert decision["action"] == "mutate"
    add = decision["add"][0]
    assert "Read-only probe" in add["title"]
    assert "Do not modify files" in add["description"]
    assert "Do not run destructive commands" in add["description"]
    assert "Do not implement" in add["description"]
    assert "Can this migration drop existing rows?" in add["description"]
    assert add["verify"] is None
    assert add["files_touched"] == []
    assert add["read_only"] is True
    assert add["clarification_probe"] is True


class _State:
    task_id = "t"
    meta = {"goal_elaborated": "goal"}


class _Dash:
    def __init__(self):
        self.updates = []

    def update(self, *args):
        self.updates.append(args)


class _Orch:
    def __init__(self):
        import threading
        self._state_lock = threading.Lock()
        self.applied = []

    def _applyReplan(self, state, decision):
        self.applied.append(decision)

    def _singleDeliverable(self, _goal):
        return False


def test_blocked_clarification_replanner_creates_readonly_probe(monkeypatch):
    monkeypatch.setattr("config.CLARIFICATION_REPLANNER_ON_BLOCK", True, raising=False)
    orch = _Orch()
    dash = _Dash()
    dual_ledger_replan.runSieAndReplan(
        orch,
        _State(),
        {"subtask_id": "st-1", "title": "Implement migration"},
        {},
        "blocked",
        False,
        "failed",
        "",
        dash,
        None,
        False,
        result=_blocked_result(),
    )
    assert len(orch.applied) == 1
    assert orch.applied[0]["reason"] == "blocked_clarification -> launch_readonly_probe"
    assert dash.updates


def test_blocked_clarification_replanner_flag_off_is_inert(monkeypatch):
    monkeypatch.setattr("config.CLARIFICATION_REPLANNER_ON_BLOCK", False, raising=False)
    monkeypatch.setattr("config.DUAL_LEDGER_PLANNER_ENABLED", False, raising=False)
    orch = _Orch()
    dash = _Dash()
    dual_ledger_replan.runSieAndReplan(
        orch,
        _State(),
        {"subtask_id": "st-1", "title": "Implement migration"},
        {},
        "blocked",
        False,
        "failed",
        "",
        dash,
        None,
        False,
        result=_blocked_result(),
    )
    assert orch.applied == []


class _LoopStub(OrchestratorRunLoopMixin):
    pass


class _FakeObs:
    def appendNote(self, *a, **k):
        pass


def test_apply_replan_persists_probe_readonly_flags(monkeypatch, tmp_path):
    monkeypatch.setattr("config.STATE_DIR", tmp_path)
    state = TaskState.create("goal", 1.0)
    host = _LoopStub()
    host.obs = _FakeObs()
    host._applyReplan(state, clarification_replan.blockedClarificationDecision(
        {"title": "Implement migration", "layer": 3}, _blocked_result()))
    probe = state.subtasks[0]
    assert probe["read_only"] is True
    assert probe["clarification_probe"] is True
    assert probe["files_touched"] == []


class _AttemptState:
    meta = {}

    def __init__(self):
        self.updated = []

    def updateSubtask(self, sid, **fields):
        self.updated.append((sid, fields))

    def getSubtask(self, _sid):
        return {"status": "in_progress"}


class _Bus:
    def isAbort(self):
        return False


class _AttemptHost(OrchestratorExecuteMixin):
    def __init__(self):
        import threading
        self._state_lock = threading.RLock()
        self.calls = 0

    def _seedResumeContext(self, _subtask):
        return None, None

    def _runOneAttempt(self, *_args, **_kwargs):
        self.calls += 1
        return (
            {"prompt": "x"},
            {"ok": False, "subtype": "blocked_clarification"},
            {"passed": False},
            "blocked",
            False,
            None,
            None,
        )

    def _translateDiscord(self, *_args):
        pass

    def _waitWhilePaused(self, *_args, **_kwargs):
        pass

    def _deadlinePassed(self, _state):
        return False


def test_blocked_clarification_does_not_consume_retry_budget(monkeypatch):
    monkeypatch.setattr("config.MAX_SUBTASK_ATTEMPTS", 3, raising=False)
    host = _AttemptHost()
    out = host._runAttemptLoop(
        _AttemptState(),
        {"subtask_id": "st-1"},
        "",
        "C:\\9to5",
        _Bus(),
        _Dash(),
        "st-1",
        None,
    )
    assert host.calls == 1
    assert out[-1] == 1
    assert out[1]["subtype"] == "blocked_clarification"
