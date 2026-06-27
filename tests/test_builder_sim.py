"""High-fidelity builder simulation: 9to5 produces REAL files in a chosen project dir and
verifies them for real -- and must NOT leave its .sc-ctx scaffolding behind."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import orchestrator as O
import platform_core.simulator.simulation as simulation
from state.task import TaskState


class TestBuilderSim(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "tasks").mkdir()
        (self.dir / "control").mkdir()
        self.proj = self.dir / "project"
        self.proj.mkdir()
        (self.proj / "README.md").write_text("pre-existing\n", encoding="utf-8")
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

    def _run(self, parallelism):
        st = TaskState.create("build (1) a (2) b (3) c", 1.0)
        st.setElaboratedGoal(st.meta["goal_raw"])
        st.save()
        orch = simulation.buildBuilderOrchestrator(str(self.proj), n_subtasks=3)
        return orch.runFull(st, work_dir=str(self.proj), auto_pr=False,
                            control_mode="watch", parallelism=parallelism)

    def test_builder_produces_and_really_verifies_files(self):
        summary = self._run(parallelism=1)
        self.assertEqual(summary["status"], "done")
        self.assertTrue(all(s["verified"] for s in summary["subtasks"]))
        for i in (1, 2, 3):
            self.assertTrue((self.proj / f"feature_{i}.py").exists())
        self.assertTrue((self.proj / "README.md").exists())   # pre-existing file untouched

    def test_no_scaffolding_left_behind(self):
        self._run(parallelism=3)   # parallel mode is what created .sc-ctx
        self.assertFalse((self.proj / ".sc-ctx").exists(), "9to5 left .sc-ctx in the project tree")


if __name__ == "__main__":
    unittest.main()
