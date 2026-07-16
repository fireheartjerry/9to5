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
from platform_core.runtime.control import ControlBus
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
            mock.patch(
                "platform_core.execution.launch_guard.requireTransactionalKernelActive",
                return_value=None,
            ),
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
        # review seam injected: this suite targets the LOOP; without it the default
        # dual-brain reviewer sees the FakeBrain's junk output as garbled -> CHALLENGED
        # (R10 fail-closed) and remediation re-runs every 3rd subtask.
        kw.setdefault("review", lambda *a, **k: {"verdict": "approved", "concerns": [],
                                                  "notes": "test stub", "stub": True})
        replan = kw.pop("replan", lambda *a, **k: {"action": "keep", "add": [], "remove": []})
        return Orchestrator(brain=FakeBrain(), obs=self._obs(), run_claude=self._fake_run_claude,
                            replan=replan,
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

    def test_parallel_executes_every_subtask_exactly_once(self):
        st = self._state([_verify_pass() for _ in range(5)])
        orch = self._orch()
        bus = ControlBus(st.task_id)
        orch.runExecutionLoop(st, "doc", str(self.dir), bus, mock.Mock(), parallelism=3)
        self.assertEqual([s["status"] for s in st.subtasks], ["done"] * 5)
        self.assertEqual(len(self.run_claude_calls), 5)
        self.assertEqual(sorted(self.run_claude_calls), sorted(set(self.run_claude_calls)))  # no double-exec

    def test_parallel_with_replan_adds_stays_consistent(self):
        # a peer worker appending subtasks (replan) mid-batch must not corrupt the run
        st = self._state([_verify_pass() for _ in range(4)])
        adds = {"n": 0}

        def replan(*a, **k):
            adds["n"] += 1
            if adds["n"] <= 2:
                return {"action": "mutate", "add": [{"title": f"x{adds['n']}", "description": "x"}], "remove": []}
            return {"action": "keep"}

        orch = self._orch(replan=replan)
        bus = ControlBus(st.task_id)
        orch.runExecutionLoop(st, "doc", str(self.dir), bus, mock.Mock(), parallelism=4)
        self.assertTrue(all(s["status"] in ("done", "removed") for s in st.subtasks))

    def test_parallel_respects_dependencies(self):
        st = TaskState.create("Build (1) base (2) dependent", 1.0)
        st.meta["goal_elaborated"] = st.meta["goal_raw"]
        st.addSubtask("base", "d", verify=_verify_pass())                       # st-001
        st.addSubtask("dependent", "d", depends_on=["st-001"], verify=_verify_pass())  # st-002
        orch = self._orch()
        bus = ControlBus(st.task_id)
        orch.runExecutionLoop(st, "doc", str(self.dir), bus, mock.Mock(), parallelism=3)
        self.assertEqual([s["status"] for s in st.subtasks], ["done", "done"])
        self.assertLess(self.run_claude_calls.index("st-001"),
                        self.run_claude_calls.index("st-002"))   # dependency order honored

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
        from platform_core.runtime.control import AbortRun
        with self.assertRaises(AbortRun):
            orch.runExecutionLoop(st, "doc", str(self.dir), bus, mock.Mock(), parallelism=1)
        # aborted before doing any work
        self.assertEqual(self.run_claude_calls, [])

    def test_enrichment_crash_preserves_committed_status(self):
        # the structural guarantee: a crash in the post-completion tail (here, replan blows up)
        # must NOT flip the subtask that already PASSED verification.
        st = self._state([_verify_pass()])

        def boom(*a, **k):
            raise RuntimeError("replan exploded")

        orch = self._orch(replan=boom)
        bus = ControlBus(st.task_id)
        orch.runExecutionLoop(st, "doc", str(self.dir), bus, mock.Mock(), parallelism=1)
        self.assertEqual(st.getSubtask("st-001")["status"], "done")

    def test_challenged_verdict_triggers_remediation_loop_stops_on_approval(self):
        # The remediation LOOP feeds concerns back, re-runs, then RE-REVIEWS; it stops as soon as
        # the reviewer approves. Here: challenged (trigger) -> 1 remediation -> approved -> stop.
        st = self._state([_verify_pass()])
        review = mock.Mock(side_effect=[
            {"verdict": "challenged", "concerns": ["add error handling"], "notes": "",
             "stub": False, "trigger_reason": "forced"},                       # triggers remediation
            {"verdict": "approved", "concerns": [], "notes": "", "stub": False},  # re-review: satisfied
        ])
        orch = self._orch(review=review)
        with mock.patch("orchestrator.adversary.shouldTrigger", return_value=(True, "forced")):
            bus = ControlBus(st.task_id)
            orch.runExecutionLoop(st, "doc", str(self.dir), bus, mock.Mock(), parallelism=1)
        self.assertEqual(st.getSubtask("st-001")["status"], "done")
        self.assertEqual(self.run_claude_calls, ["st-001", "st-001"])   # original + 1 remediation (stopped early)
        kinds = [n["kind"] for n in st.data["notifications"]]
        self.assertIn("adversary_remediation", kinds)

    def test_remediation_loop_is_bounded(self):
        # A reviewer that NEVER approves must not loop forever: capped at
        # ADVERSARY_REMEDIATION_MAX_ATTEMPTS remediations (here forced to 2) + the original run.
        st = self._state([_verify_pass()])
        review = mock.Mock(return_value={"verdict": "challenged", "concerns": ["still bad"],
                                         "notes": "", "stub": False, "trigger_reason": "forced"})
        orch = self._orch(review=review)
        with mock.patch("orchestrator.adversary.shouldTrigger", return_value=(True, "forced")), \
                mock.patch.object(config, "ADVERSARY_REMEDIATION_MAX_ATTEMPTS", 2):
            bus = ControlBus(st.task_id)
            orch.runExecutionLoop(st, "doc", str(self.dir), bus, mock.Mock(), parallelism=1)
        self.assertEqual(st.getSubtask("st-001")["status"], "done")     # never downgrades the pass
        self.assertEqual(self.run_claude_calls, ["st-001", "st-001", "st-001"])  # original + 2 capped

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
