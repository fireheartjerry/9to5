"""scripts/repo_health.py gathers a valid cold-start snapshot."""
import importlib.util
import unittest
from pathlib import Path

_PATH = Path(__file__).resolve().parent.parent.parent / "scripts" / "repo_health.py"
_spec = importlib.util.spec_from_file_location("repo_health", _PATH)
repo_health = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(repo_health)


class TestRepoHealth(unittest.TestCase):
    def test_gather_has_expected_keys(self):
        snap = repo_health.gather()
        for key in ("python", "branch", "dirty_files", "test_count",
                    "recent_traces", "configs_present", "suggested_commands"):
            self.assertIn(key, snap, key)

    def test_test_count_is_positive(self):
        # This very repo has many tests/test_*.py, including this file.
        self.assertGreater(repo_health.gather()["test_count"], 0)

    def test_render_is_a_nonempty_string(self):
        text = repo_health.render(repo_health.gather())
        self.assertIn("9to5 repo health", text)
        self.assertIn("next:", text)

    def test_main_runs_clean(self):
        self.assertEqual(repo_health.main([]), 0)
        self.assertEqual(repo_health.main(["--json"]), 0)
