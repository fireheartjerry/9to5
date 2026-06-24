# tests/test_identity.py
"""The SELF manifest: canonicalization + role classification."""
import os, tempfile, unittest
from pathlib import Path

import identity


class TestCanonical(unittest.TestCase):
    def test_collapses_dotdot_and_normalizes_case(self):
        raw = r"C:\9to5\agents\..\config.py"
        self.assertEqual(identity._canonical(raw), identity._canonical(r"C:\9to5\config.py"))

    def test_absolute_and_relative_to_root_match(self):
        # A bare 'config.py' resolved against the project root equals the absolute form.
        os.chdir(identity.PROJECT_ROOT)
        self.assertEqual(identity._canonical("config.py"),
                         identity._canonical(str(identity.PROJECT_ROOT / "config.py")))


if __name__ == "__main__":
    unittest.main()
