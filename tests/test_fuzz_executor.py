"""Property-based fuzz of the executor result. _executeSubtask consumes the run_claude
return via result.get(...); a malformed result (None, non-dict, missing keys, wrong types)
must degrade gracefully -- the run always reaches a valid terminal state, never crashes the
core to 'blocked', and never raises out of runFull.
"""
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import orchestrator as O
import platform_core.simulator.simulation as simulation
from orchestrator import Orchestrator
from state.task import TaskState

_GRACEFUL_TERMINAL = {"done", "complete", "partial", "failed", "aborted"}


def _fuzz_executor(rng):
    def run_claude(spec, **kw):
        shape = rng.choice(["valid", "none", "str", "int", "list", "empty", "partial", "mistyped"])
        if shape == "valid":
            return {"ok": True, "returncode": 0, "stdout": "ok", "is_error": False, "session_id": None}
        if shape == "none":
            return None
        if shape == "str":
            return "not a dict"
        if shape == "int":
            return 42
        if shape == "list":
            return [1, 2, 3]
        if shape == "empty":
            return {}
        if shape == "partial":
            return {"ok": rng.choice([True, False, None, "yes"])}
        return {"ok": "truthy", "returncode": "x", "stdout": 5, "stderr": {"a": 1},
                "is_error": "maybe", "session_id": ["s"]}
    return run_claude


class TestExecutorFuzz(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "tasks").mkdir()
        (self.dir / "control").mkdir()
        self.work = self.dir / "work"
        self.work.mkdir()
        self._patches = [
            mock.patch.object(config, "STATE_DIR", self.dir / "tasks"),
            mock.patch.object(config, "CONTROL_DIR", self.dir / "control"),
            mock.patch.object(config, "WEB_DASHBOARD", False),
            mock.patch.object(config, "DISCORD_DASHBOARD", False),
            mock.patch.object(O, "refreshClaudeKnowledge", lambda *a, **k: ""),
            mock.patch.object(O, "startWebDashboard", lambda *a, **k: None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_malformed_executor_results_terminate_gracefully(self):
        bad = []
        for seed in range(80):
            rng = random.Random(seed * 11 + 3)
            st = TaskState.create("build (1) a (2) b (3) c", 1.0)
            st.setElaboratedGoal(st.meta["goal_raw"])
            st.save()
            orch = Orchestrator(brain=simulation.SimBrain(3), obs=simulation.SimObs(),
                                run_claude=_fuzz_executor(rng), replan=simulation.simReplan,
                                review=simulation.simReview)
            try:
                summary = orch.runFull(st, work_dir=str(self.work), auto_pr=False, control_mode="watch")
                if summary["status"] not in _GRACEFUL_TERMINAL:
                    bad.append((seed, summary["status"], summary.get("reason")))
            except Exception as e:  # noqa: BLE001
                bad.append((seed, "RAISED", repr(e)))
        self.assertEqual(bad, [], f"executor fuzz produced bad outcomes: {bad[:8]}")
