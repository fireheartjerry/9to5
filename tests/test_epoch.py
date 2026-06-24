# tests/test_epoch.py
"""Primitive 2 -- the per-run epoch pin + self.code fingerprint."""
import tempfile, unittest
from pathlib import Path
from unittest import mock

import epoch


class TestFingerprint(unittest.TestCase):
    def test_fingerprint_changes_when_a_self_code_file_changes(self):
        f = Path(tempfile.mkdtemp()) / "m.py"
        f.write_text("x = 1", encoding="utf-8")
        with mock.patch("identity.selfCodeFiles", return_value=[str(f)]):
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


if __name__ == "__main__":
    unittest.main()
