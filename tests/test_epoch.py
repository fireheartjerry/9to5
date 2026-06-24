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


if __name__ == "__main__":
    unittest.main()
