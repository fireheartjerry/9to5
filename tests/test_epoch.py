# tests/test_epoch.py
"""Primitive 2 -- the per-run epoch pin + self.code fingerprint."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import platform_core.core.epoch as epoch


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
        import config
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


if __name__ == "__main__":
    unittest.main()
