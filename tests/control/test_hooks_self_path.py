"""hooks.py must add ITS OWN repo root to sys.path (derived from __file__), never a
hardcoded foreign install root -- otherwise a worktree imports the wrong tree (R10)."""
import sys
import unittest
from pathlib import Path

from agents import hooks


class TestHooksSelfPath(unittest.TestCase):
    def test_inserts_own_tree_root_not_a_hardcoded_path(self):
        own_root = str(Path(hooks.__file__).resolve().parent.parent)
        # the module's own repo root must be on sys.path (so it imports its OWN siblings)
        self.assertIn(own_root, [str(Path(p).resolve()) for p in sys.path if p])

    def test_source_does_not_hardcode_install_root_for_syspath(self):
        src = Path(hooks.__file__).read_text(encoding="utf-8")
        # The sys.path insert must NOT hardcode a literal drive path.
        self.assertNotIn('sys.path.insert(0, r"C:\\9to5")', src)
        self.assertNotIn("sys.path.insert(0, r'C:\\9to5')", src)
