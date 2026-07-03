"""Regression test (fresh bug hunt): _executeSubtask must tear down its provisioned Epic-8
environment on EVERY exit path, including an exception (e.g. AbortRun) raised out of
_runSubtaskAttempts -- previously finalizeQuietly only ran on the two normal-return paths, so an
abort mid-attempt leaked a Docker container (never self-exits despite --rm) or a remote host's
/tmp tree."""
import threading
import unittest
from unittest import mock

from platform_core.execution.environment import EnvHandle
from platform_core.orchestration.execute_mixin import OrchestratorExecuteMixin


class _Host(OrchestratorExecuteMixin):
    def __init__(self):
        self._state_lock = threading.Lock()

    def _execCwd(self, state, sid, work_dir):
        return work_dir


class _FakeDashboard:
    def update(self, *a, **k):
        pass


class _FakeState:
    def __init__(self):
        self.subtasks = [{"subtask_id": "st-001", "status": "in_progress", "title": "do x"}]

    def getSubtask(self, sid):
        return next((s for s in self.subtasks if s["subtask_id"] == sid), None)

    def updateSubtask(self, sid, **fields):
        self.getSubtask(sid).update(fields)

    def addNotification(self, *a, **k):
        pass


class TestFinalizeAlwaysRuns(unittest.TestCase):
    def setUp(self):
        self.host = _Host()
        self.state = _FakeState()
        self.subtask = self.state.subtasks[0]
        self.handle = EnvHandle(work_dir="/repo", backend="local", meta={}, capabilities=None)

    def test_finalize_runs_when_attempts_raise(self):
        finalize = mock.patch("platform_core.execution.wiring.finalizeQuietly")
        provision = mock.patch("platform_core.execution.wiring.provisionForSubtask",
                               return_value=(object(), self.handle, (object(), self.handle), "/repo"))
        with finalize as fin, provision, \
             mock.patch.object(self.host, "_runSubtaskAttempts",
                               side_effect=RuntimeError("boom (stands in for AbortRun)")):
            with self.assertRaises(RuntimeError):
                self.host._executeSubtask(self.state, self.subtask, "arch doc", "/repo",
                                          bus=mock.Mock(), dashboard=_FakeDashboard(), position=0)
        fin.assert_called_once()

    def test_finalize_runs_on_normal_completion(self):
        finalize = mock.patch("platform_core.execution.wiring.finalizeQuietly")
        provision = mock.patch("platform_core.execution.wiring.provisionForSubtask",
                               return_value=(object(), self.handle, (object(), self.handle), "/repo"))
        with finalize as fin, provision, \
             mock.patch.object(self.host, "_runSubtaskAttempts",
                               return_value=({"prompt": "x"}, {"ok": True}, {"passed": True},
                                            "combined", True, 1)), \
             mock.patch.object(self.host, "_surfaceSubtaskPass"), \
             mock.patch.object(self.host, "_postSubtaskEnrich"), \
             mock.patch("platform_core.orchestration.execute_mixin.discord"), \
             mock.patch("platform_core.orchestration.execute_mixin.cast"):
            result = self.host._executeSubtask(self.state, self.subtask, "arch doc", "/repo",
                                               bus=mock.Mock(), dashboard=_FakeDashboard(), position=0)
        self.assertEqual(result, "done")
        fin.assert_called_once()


if __name__ == "__main__":
    unittest.main()
