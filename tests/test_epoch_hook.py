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

    def test_core_lock_uses_pinned_epoch_not_live_config(self):
        # Epoch pins SELFMOD_ALLOW_CORE=False + a core-file list. A mid-run flip of live
        # config to allow_core / a different core list must NOT change what THIS run enforces.
        st = TaskState.create("g", 1.0)
        with mock.patch.object(config, "SELFMOD_ALLOW_CORE", False), \
             mock.patch.object(config, "CORE_PROTECTED_FILES", ("orchestrator.py", "config.py")):
            st.setEpoch(epoch.snapshot(universe={"hard_boundaries": []}))
        # live config now flips to allow_core=True with an empty core list (a mid-run edit)
        with mock.patch.object(config, "SELFMOD_ALLOW_CORE", True), \
             mock.patch.object(config, "CORE_PROTECTED_FILES", ()):
            allow_core, core_files = hooks._coreLockFor(st)
        self.assertFalse(allow_core)                       # pinned False wins
        self.assertIn("config.py", set(core_files))         # pinned core list wins

    def test_core_lock_falls_back_to_live_config_without_epoch(self):
        st = TaskState.create("g", 1.0)   # no epoch
        with mock.patch.object(config, "SELFMOD_ALLOW_CORE", True), \
             mock.patch.object(config, "CORE_PROTECTED_FILES", ("config.py",)):
            allow_core, core_files = hooks._coreLockFor(st)
        self.assertTrue(allow_core)                         # legacy: live value
        self.assertIn("config.py", set(core_files))
