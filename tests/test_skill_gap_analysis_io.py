#!/usr/bin/env python3
"""
tests/test_skill_gap_analysis_io.py
Tests for workflows/skill-gap-analysis.py — I/O and reporting layer.

Validates:
  - loadTaskHistory loads JSON task files correctly.
  - loadSkillInventory reads skills from the skills directory.
  - printReport produces expected output sections.
  - main() returns appropriate exit codes.

Split from test-skill-gap-analysis.py (was 420 lines).
Run: python -m pytest tests/test_skill_gap_analysis_io.py
"""
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Load the module under test (filename contains hyphens → importlib required)
# ---------------------------------------------------------------------------
_SRC = pathlib.Path("C:/9to5/workflows/skill-gap-analysis.py")
if not _SRC.exists():
    raise FileNotFoundError(f"Module not found: {_SRC}")

_spec = importlib.util.spec_from_file_location("skill_gap_analysis_wf", _SRC)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# aliases
_stemTokens        = _mod._stemTokens
_skillNameTokens   = _mod._skillNameTokens
buildDemandCounter = _mod.buildDemandCounter
scoreDomains       = _mod.scoreDomains
printReport        = _mod.printReport
loadSkillInventory = _mod.loadSkillInventory
loadTaskHistory    = _mod.loadTaskHistory
DOMAIN_MAP         = _mod.DOMAIN_MAP


# ---------------------------------------------------------------------------
# loadTaskHistory
# ---------------------------------------------------------------------------
class TestLoadTaskHistory(unittest.TestCase):
    def test_nonexistent_dir_returns_empty(self):
        with patch.object(_mod, "TASKS_DIR", pathlib.Path("/nonexistent/path/xyz")):
            result = loadTaskHistory()
        self.assertEqual(result, [])

    def test_empty_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(_mod, "TASKS_DIR", pathlib.Path(tmp)):
                result = loadTaskHistory()
        self.assertEqual(result, [])

    def test_valid_json_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            task = {"meta": {"goal_raw": "test task"}, "plan": {}}
            (pathlib.Path(tmp) / "task-001.json").write_text(json.dumps(task))
            with patch.object(_mod, "TASKS_DIR", pathlib.Path(tmp)):
                result = loadTaskHistory()
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["meta"]["goal_raw"], "test task")

    def test_bad_json_skipped_with_warning(self):
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "bad.json").write_text("{ not valid json }")
            with patch.object(_mod, "TASKS_DIR", pathlib.Path(tmp)):
                with patch("sys.stderr", new_callable=io.StringIO) as mock_err:
                    result = loadTaskHistory()
                    err_output = mock_err.getvalue()
        self.assertEqual(result, [])
        self.assertIn("warn", err_output.lower())

    def test_multiple_tasks_all_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(3):
                (pathlib.Path(tmp) / f"task-{i:03d}.json").write_text(
                    json.dumps({"meta": {"goal_raw": f"goal {i}"}, "plan": {}})
                )
            with patch.object(_mod, "TASKS_DIR", pathlib.Path(tmp)):
                result = loadTaskHistory()
        self.assertEqual(len(result), 3)


# ---------------------------------------------------------------------------
# loadSkillInventory
# ---------------------------------------------------------------------------
class TestLoadSkillInventory(unittest.TestCase):
    def test_nonexistent_dir_returns_empty(self):
        with patch.object(_mod, "SKILLS_DIR", pathlib.Path("/nonexistent/xyz")):
            result = loadSkillInventory()
        self.assertEqual(result, {})

    def test_md_file_added_as_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / "debugging.md").write_text("## Debug skill content for trace replay")
            with patch.object(_mod, "SKILLS_DIR", p):
                inventory = loadSkillInventory()
        self.assertIn("debugging", inventory)
        self.assertIsInstance(inventory["debugging"], set)

    def test_py_files_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / "helper.py").write_text("# python file")
            with patch.object(_mod, "SKILLS_DIR", p):
                inventory = loadSkillInventory()
        self.assertNotIn("helper", inventory)

    def test_hidden_files_skipped(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / ".hidden.md").write_text("# hidden")
            with patch.object(_mod, "SKILLS_DIR", p):
                inventory = loadSkillInventory()
        self.assertNotIn(".hidden", inventory)

    def test_subdirectory_added_as_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            skill_dir = p / "testing"
            skill_dir.mkdir()
            (skill_dir / "skill.md").write_text("# Testing skill")
            with patch.object(_mod, "SKILLS_DIR", p):
                inventory = loadSkillInventory()
        self.assertIn("testing", inventory)

    def test_skill_tokens_include_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / "workflow-engine.md").write_text("some content here")
            with patch.object(_mod, "SKILLS_DIR", p):
                inventory = loadSkillInventory()
        self.assertIn("workflow-engine", inventory)
        # name tokens derived from file content + name
        tokens = inventory["workflow-engine"]
        self.assertTrue(any("workflow" in t or t.startswith("workflow") for t in tokens))


# ---------------------------------------------------------------------------
# printReport
# ---------------------------------------------------------------------------
class TestPrintReport(unittest.TestCase):
    def _make_rows(self):
        return [
            {"domain": "testing", "demand": 10, "covered_by": ["test-helper"], "gap_score": 5.0},
            {"domain": "security", "demand": 8, "covered_by": [], "gap_score": 8.0},
            {"domain": "memory", "demand": 0, "covered_by": [], "gap_score": 0.0},
        ]

    def _capture(self, rows, inventory, task_count):
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            printReport(rows, inventory, task_count)
        return buf.getvalue()

    def test_header_present(self):
        out = self._capture(self._make_rows(), {"test-helper": set()}, 5)
        self.assertIn("SKILL GAP REPORT", out)

    def test_task_count_shown(self):
        out = self._capture(self._make_rows(), {"test-helper": set()}, 7)
        self.assertIn("7", out)

    def test_inventory_count_shown(self):
        inv = {"test-helper": set(), "debug-tool": set()}
        out = self._capture(self._make_rows(), inv, 0)
        self.assertIn("2", out)

    def test_critical_gap_section_for_demanded_uncovered(self):
        out = self._capture(self._make_rows(), {}, 1)
        self.assertIn("Critical Gaps", out)
        self.assertIn("security", out)

    def test_latent_gap_section_for_zero_demand_uncovered(self):
        out = self._capture(self._make_rows(), {"test-helper": set()}, 1)
        self.assertIn("Latent", out)
        self.assertIn("memory", out)

    def test_none_section_when_no_uncovered(self):
        rows = [{"domain": "testing", "demand": 5, "covered_by": ["a", "b"], "gap_score": 0.0}]
        out = self._capture(rows, {"a": set(), "b": set()}, 1)
        self.assertNotIn("Critical Gaps", out)


# ---------------------------------------------------------------------------
# main()
# ---------------------------------------------------------------------------
class TestMain(unittest.TestCase):
    def test_returns_zero_with_valid_skills_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / "debugging.md").write_text("debug trace replay inspect")
            with patch.object(_mod, "SKILLS_DIR", p):
                with patch.object(_mod, "TASKS_DIR", pathlib.Path("/nonexistent/xyz")):
                    with patch("sys.stdout", io.StringIO()):
                        result = _mod.main()
        self.assertEqual(result, 0)

    def test_returns_one_when_no_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            # empty dir → no skills
            with patch.object(_mod, "SKILLS_DIR", pathlib.Path(tmp)):
                with patch("sys.stderr", io.StringIO()):
                    result = _mod.main()
        self.assertEqual(result, 1)

    def test_returns_zero_with_tasks_and_skills(self):
        with tempfile.TemporaryDirectory() as skills_tmp:
            with tempfile.TemporaryDirectory() as tasks_tmp:
                sp = pathlib.Path(skills_tmp)
                tp = pathlib.Path(tasks_tmp)
                (sp / "testing.md").write_text("test pytest validate")
                task = {
                    "meta": {"goal_raw": "add automated tests", "goal_elaborated": ""},
                    "plan": {"subtasks": [{"title": "write tests", "description": "pytest"}]}
                }
                (tp / "task-001.json").write_text(json.dumps(task))
                with patch.object(_mod, "SKILLS_DIR", sp):
                    with patch.object(_mod, "TASKS_DIR", tp):
                        with patch("sys.stdout", io.StringIO()):
                            result = _mod.main()
        self.assertEqual(result, 0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
        TestLoadTaskHistory,
        TestLoadSkillInventory,
        TestPrintReport,
        TestMain,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
