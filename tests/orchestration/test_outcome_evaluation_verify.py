from platform_core.orchestration.run_phase_mixin import OrchestratorRunPhaseMixin


class _State:
    def __init__(self):
        self.meta = {"outcome_evaluation_verify": {"cmd": "python -m pytest test_x.py -q", "expect": "exit_zero"}}
        self.subtasks = []
    def addSubtask(self, title, description, **kwargs):
        item = {"title": title, "description": description, **kwargs}
        self.subtasks.append(item)
        return item
    def addNotification(self, *_args):
        pass


def test_outcome_evaluation_uses_declared_verify(monkeypatch):
    monkeypatch.setattr("platform_core.orchestration.plan_concurrency.normalizePlanConcurrency", lambda plan: plan)
    state = _State()
    OrchestratorRunPhaseMixin()._persistPlanSubtasks(state, [{"title": "x", "description": "x", "verify": {"cmd": "wrong", "expect": "exit_zero"}}])
    assert state.subtasks[0]["verify"]["cmd"] == "python -m pytest test_x.py -q"
