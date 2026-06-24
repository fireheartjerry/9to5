import tempfile, unittest
from pathlib import Path
from unittest import mock

import config, epoch
from state.task import TaskState
from agents import hooks


class TestHookReadsEpoch(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        mock.patch.object(config, "STATE_DIR", self.dir).start()

    def tearDown(self):
        mock.patch.stopall()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_boundary_set_comes_from_pinned_epoch(self):
        st = TaskState.create("g", 1.0)
        snap = epoch.snapshot(universe={"hard_boundaries": ["secret_pinned.py"]})
        st.setEpoch(snap)
        boundaries = hooks._boundarySetFor(st)
        self.assertIn("secret_pinned.py", boundaries)

    def test_baseline_still_present_without_epoch(self):
        # Legacy task with no epoch: the always-on baseline boundaries still apply.
        st = TaskState.create("g", 1.0)
        boundaries = hooks._boundarySetFor(st)
        # at least one of the default baseline entries is present (fail-closed)
        self.assertTrue(any(b in boundaries for b in getattr(config, "UNIVERSE_DEFAULT_HARD_BOUNDARIES", ())))
