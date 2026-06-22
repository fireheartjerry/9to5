"""End-to-end dry-run: the FULL pipeline (architect -> plan -> execute -> verify ->
complete) through the real runFull, wired entirely with simulation doubles. This is the
ultimate integration test -- it exercises every phase with no external service."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import simulation
from state.task import TaskState


class TestDryRun(unittest.TestCase):
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
            mock.patch("orchestrator.refreshClaudeKnowledge", lambda *a, **k: ""),
            mock.patch("orchestrator.startWebDashboard", lambda *a, **k: None),
        ]
        for p in self._patches:
            p.start()

    def tearDown(self):
        for p in self._patches:
            p.stop()

    def test_full_simulated_run_completes(self):
        st = TaskState.create("build a calculator", 1.0)
        st.setElaboratedGoal("build a calculator")
        st.save()
        orch = simulation.buildOrchestrator(n_subtasks=3)
        summary = orch.runFull(st, work_dir=str(self.work), auto_pr=False, control_mode="watch")
        self.assertEqual(summary["status"], "done")
        self.assertEqual(len(summary["subtasks"]), 3)
        self.assertTrue(all(s["status"] == "done" for s in summary["subtasks"]))
        self.assertTrue(all(s["verified"] for s in summary["subtasks"]))
        self.assertTrue(summary["pr"]["skipped"])

    def test_run_is_not_self_referential_in_temp_dir(self):
        # guards the dry-run side-effect fix: a temp work_dir must not trip self-ref detection
        st = TaskState.create("build a calculator", 1.0)
        st.setElaboratedGoal("build a calculator")
        st.save()
        simulation.buildOrchestrator(n_subtasks=1).runFull(
            st, work_dir=str(self.work), auto_pr=False, control_mode="watch")
        self.assertFalse(st.meta.get("is_self_referential"))


if __name__ == "__main__":
    unittest.main()
