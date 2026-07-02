"""Flag-off path is byte-identical to _runAttemptLoop; flag-on + eligible routes to runForked."""
import config
from platform_core.orchestration.execute_mixin import OrchestratorExecuteMixin


class Harness(OrchestratorExecuteMixin):
    def __init__(self):
        import threading
        self._state_lock = threading.RLock()
        self.attempt_called = False
        self.fork_called = False

    def _runAttemptLoop(self, state, subtask, architect_doc, exec_cwd, bus, dashboard, sid, verify_spec):
        self.attempt_called = True
        return ("spec", "result", {"passed": True}, "combined", True, 1)


class FakeState:
    def __init__(self, **meta):
        self.meta = {"goal_elaborated": "build a feature spanning multiple files",
                     "is_self_referential": False, **meta}


def test_flag_off_calls_attempt_loop_only(monkeypatch):
    monkeypatch.setattr(config, "SOLUTION_FORK_ENABLED", False)
    h = Harness()
    sub = {"subtask_id": "st-001", "fork_eligible": True}
    tup = h._runSubtaskAttempts(FakeState(), sub, "ARCH", "/cwd", None, None, "st-001", {"cmd": "x"})
    assert h.attempt_called is True and h.fork_called is False
    assert tup == ("spec", "result", {"passed": True}, "combined", True, 1)


def test_flag_on_eligible_routes_to_runforked(monkeypatch):
    monkeypatch.setattr(config, "SOLUTION_FORK_ENABLED", True)
    import platform_core.orchestration.solution_space as ss
    monkeypatch.setattr(ss, "worktreeIsolated", lambda: True)

    def fake_runforked(orch, *a, **k):
        orch.fork_called = True
        return ("fspec", "fresult", {"passed": True}, "fcombined", True, 1)
    monkeypatch.setattr(ss, "runForked", fake_runforked)

    h = Harness()
    sub = {"subtask_id": "st-001", "fork_eligible": True}
    tup = h._runSubtaskAttempts(FakeState(), sub, "ARCH", "/cwd", None, None, "st-001", {"cmd": "x"})
    assert h.fork_called is True and h.attempt_called is False
    assert tup[0] == "fspec"
