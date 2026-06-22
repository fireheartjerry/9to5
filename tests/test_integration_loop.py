"""Integration test: drive the REAL orchestration loop (runExecutionLoop ->
_executeSubtask -> verifier) with injected fakes for the brain, the Claude executor,
the replanner, and Obsidian. No Ollama / Claude CLI / network is touched.

This is the coverage that was missing: the two worst bugs this codebase has had
(the mid-subtask poll arity crash and the malformed-replan crash) both lived in
this loop and were invisible to unit tests because the loop couldn't be instantiated.
"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from control import ControlBus
from orchestrator import Orchestrator
from state.task import TaskState


class FakeBrain:
    """Stands in for ollama.Client: every .chat() returns a minimal invocation spec."""
    def __init__(self, spec=None):
        self.spec = spec or {"prompt": "do the work", "effort_level": "default"}
        self.calls = 0

    def chat(self, *args, **kwargs):
        self.calls += 1
        return {"message": {"content": json.dumps(self.spec)}}


def _verify_pass():
    return {"cmd": "python -c \"print('ok')\"", "expect": "exit_zero"}


def _verify_fail():
    # strict => the behavioral repair fallback is skipped, so this fails deterministically
    return {"cmd": "python -c \"import sys; sys.exit(1)\"", "expect": "exit_zero", "strict": True}


class TestExecutionLoop(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.state_dir = self.dir / "tasks"
        self.ctrl_dir = self.dir / "control"
        self.state_dir.mkdir()
        self.ctrl_dir.mkdir()
        self._patches = [
            mock.patch.object(config, "STATE_DIR", self.state_dir),
            mock.patch.object(config, "CONTROL_DIR", self.ctrl_dir),
        ]
        for p in self._patches:
            p.start()
        self.run_claude_calls = []

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def _fake_run_claude(self, spec, **kwargs):
        self.run_claude_calls.append(kwargs.get("subtask", {}).get("subtask_id"))
        return {"ok": True, "returncode": 0, "stdout": "implemented it", "is_error": False,
                "session_id": None}

    def _obs(self):
        obs = mock.Mock()
        obs.writeNote.return_value = {"ok": True, "rel_path": "note.md"}
        obs.appendNote.return_value = {"ok": True}
        obs.readNote.return_value = None
        return obs

    def _orch(self, **kw):
        return Orchestrator(brain=FakeBrain(), obs=self._obs(), run_claude=self._fake_run_claude,
                            replan=lambda *a, **k: {"action": "keep", "add": [], "remove": []},
                            **kw)

    def _state(self, verifies):
        st = TaskState.create("Build two things (1) alpha (2) beta", 1.0)
        st.meta["goal_elaborated"] = st.meta["goal_raw"]
        for i, v in enumerate(verifies, 1):
            st.addSubtask(f"subtask {i}", f"do thing {i}", verify=v)
        return st

    def test_happy_path_all_subtasks_done(self):
        st = self._state([_verify_pass(), _verify_pass()])
        orch = self._orch()
        bus = ControlBus(st.task_id)
        orch.runExecutionLoop(st, "architecture doc", str(self.dir), bus, mock.Mock(), parallelism=1)
        statuses = [s["status"] for s in st.subtasks]
        self.assertEqual(statuses, ["done", "done"])
        self.assertEqual(self.run_claude_calls, ["st-001", "st-002"])  # both actually executed

    def test_failing_verify_ends_failed_without_hanging(self):
        st = self._state([_verify_fail()])
        orch = self._orch()
        bus = ControlBus(st.task_id)
        orch.runExecutionLoop(st, "doc", str(self.dir), bus, mock.Mock(), parallelism=1)
        self.assertEqual(st.getSubtask("st-001")["status"], "failed")
        # retried up to MAX_SUBTASK_ATTEMPTS (each attempt re-invokes the executor)
        self.assertEqual(len(self.run_claude_calls), config.MAX_SUBTASK_ATTEMPTS)

    def test_abort_between_subtasks_stops_the_loop(self):
        st = self._state([_verify_pass(), _verify_pass()])
        orch = self._orch()
        bus = ControlBus(st.task_id)
        bus.requestAbort()
        from control import AbortRun
        with self.assertRaises(AbortRun):
            orch.runExecutionLoop(st, "doc", str(self.dir), bus, mock.Mock(), parallelism=1)
        # aborted before doing any work
        self.assertEqual(self.run_claude_calls, [])

    def test_adversary_trigger_does_not_fail_a_passed_subtask(self):
        # force the adversary to fire and CHALLENGE; the subtask still PASSED verification,
        # so its committed status must remain done (the verdict never corrupts the result).
        st = self._state([_verify_pass()])
        review = mock.Mock(return_value={"verdict": "challenged", "trigger_reason": "test",
                                         "concerns": ["weak"], "notes": "", "stub": False})
        orch = self._orch(review=review)
        with mock.patch("orchestrator.adversary.shouldTrigger", return_value=(True, "forced")):
            bus = ControlBus(st.task_id)
            orch.runExecutionLoop(st, "doc", str(self.dir), bus, mock.Mock(), parallelism=1)
        self.assertEqual(st.getSubtask("st-001")["status"], "done")
        self.assertTrue(review.called)


if __name__ == "__main__":
    unittest.main()
