import tempfile, unittest
from pathlib import Path
from unittest import mock

import config
import platform_core.core.epoch as epoch
from state.task import TaskState
import orchestrator


class TestRunMarksDivergence(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        mock.patch.object(config, "STATE_DIR", self.dir).start()

    def tearDown(self):
        mock.patch.stopall()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_code_diverged_set_when_self_code_changes_after_snapshot(self):
        f = Path(tempfile.mkdtemp()) / "m.py"
        f.write_text("x = 1", encoding="utf-8")
        with mock.patch("platform_core.core.identity.selfCodeFiles", return_value=[str(f)]):
            st = TaskState.create("g", 1.0)
            st.setEpoch(epoch.snapshot(universe={}))
            f.write_text("x = 2", encoding="utf-8")           # a self-edit mid-run
            diverged = orchestrator._checkCodeDivergence(st)  # called at subtask boundary
        self.assertTrue(diverged)
        self.assertTrue(st.meta.get("code_diverged"))

    def test_no_divergence_when_code_unchanged(self):
        f = Path(tempfile.mkdtemp()) / "m.py"
        f.write_text("x = 1", encoding="utf-8")
        with mock.patch("platform_core.core.identity.selfCodeFiles", return_value=[str(f)]):
            st = TaskState.create("g", 1.0)
            st.setEpoch(epoch.snapshot(universe={}))
            diverged = orchestrator._checkCodeDivergence(st)
        self.assertFalse(diverged)
        self.assertFalse(st.meta.get("code_diverged"))
