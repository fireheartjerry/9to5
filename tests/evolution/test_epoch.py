# tests/test_epoch.py
"""Primitive 2 -- the per-run epoch pin + self.code fingerprint.

Consolidated from test_epoch.py, test_epoch_divergence.py, test_epoch_hook.py,
and test_epoch_state.py: all four exercise platform_core.core.epoch, either
directly (fingerprint/snapshot/diverged) or through its integration points
(TaskState.meta, orchestrator divergence checks, agents.hooks boundary/core-lock
resolution).
"""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
import platform_core.core.epoch as epoch
from state.task import TaskState
import orchestrator
from agents import hooks


class TestFingerprint(unittest.TestCase):
    def test_fingerprint_changes_when_a_self_code_file_changes(self):
        f = Path(tempfile.mkdtemp()) / "m.py"
        f.write_text("x = 1", encoding="utf-8")
        with mock.patch("platform_core.core.identity.selfCodeFiles", return_value=[str(f)]):
            before = epoch.fingerprint()
            f.write_text("x = 2", encoding="utf-8")
            after = epoch.fingerprint()
        self.assertNotEqual(before["files"][str(f).lower()], after["files"][str(f).lower()])


class TestSnapshot(unittest.TestCase):
    def test_snapshot_is_immutable_under_later_config_change(self):
        with mock.patch.object(config, "MAX_SUBTASK_ATTEMPTS", 3):
            snap = epoch.snapshot(universe={"hard_boundaries": [".env"]})
        with mock.patch.object(config, "MAX_SUBTASK_ATTEMPTS", 99):
            # The snapshot captured 3 at snapshot time and does not see the later 99.
            self.assertEqual(snap.config_knobs["MAX_SUBTASK_ATTEMPTS"], 3)

    def test_snapshot_roundtrips_through_meta_dict(self):
        snap = epoch.snapshot(universe={"hard_boundaries": [".env"]})
        self.assertEqual(epoch.Epoch.fromDict(snap.toDict()).universe, snap.universe)

    def test_snapshot_carries_boundary_set(self):
        snap = epoch.snapshot(universe={"hard_boundaries": ["state/tasks", "secret.py"]})
        self.assertIn("secret.py", snap.universe["hard_boundaries"])

    def test_todict_is_independent_of_the_live_epoch(self):
        # Mutating the exported dict must NOT corrupt the live Epoch (which would break diverged()).
        snap = epoch.snapshot(universe={"hard_boundaries": [".env"]})
        d = snap.toDict()
        d["code"]["files"]["INJECTED"] = "deadbeef"
        d["universe"]["hard_boundaries"].append("INJECTED")
        self.assertNotIn("INJECTED", snap.code["files"])
        self.assertNotIn("INJECTED", snap.universe["hard_boundaries"])


class TestDiverged(unittest.TestCase):
    def test_diverged_true_after_a_self_code_edit(self):
        f = Path(tempfile.mkdtemp()) / "m.py"
        f.write_text("x = 1", encoding="utf-8")
        with mock.patch("platform_core.core.identity.selfCodeFiles", return_value=[str(f)]):
            snap = epoch.snapshot(universe={})
            self.assertFalse(epoch.diverged(snap))
            f.write_text("x = 2", encoding="utf-8")
            self.assertTrue(epoch.diverged(snap))


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


class TestEpochInMeta(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        mock.patch.object(config, "STATE_DIR", self.dir).start()

    def tearDown(self):
        mock.patch.stopall()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_meta_has_epoch_field_default_none(self):
        st = TaskState.create("g", 1.0)
        self.assertIn("epoch", st.meta)
        self.assertIsNone(st.meta["epoch"])

    def test_set_epoch_persists(self):
        st = TaskState.create("g", 1.0)
        snap = epoch.snapshot(universe={"hard_boundaries": [".env"]})
        st.setEpoch(snap)
        self.assertEqual(TaskState.load(st.task_id).meta["epoch"]["universe"]["hard_boundaries"],
                         [".env"])
