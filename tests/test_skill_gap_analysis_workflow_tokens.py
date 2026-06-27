#!/usr/bin/env python3
"""
tests/test_skill_gap_analysis_workflow_tokens.py
Acceptance tests for skill-gap-analysis workflow — token/inventory/task-loading layer.

Validates:
  - _stemTokens and _skillNameTokens produce correct results.
  - loadSkillInventory skips .py / dotfiles / hidden entries.
  - loadTaskHistory (parallel loading via ThreadPoolExecutor) works correctly.

Split from test_skill_gap_analysis_workflow.py (was 430 lines).
Run: python -m pytest tests/test_skill_gap_analysis_workflow_tokens.py
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
# Load module under test (filename contains hyphens — importlib required)
# ---------------------------------------------------------------------------
_SRC = pathlib.Path("C:/9to5/workflows/skill-gap-analysis.py")
if not _SRC.exists():
    raise FileNotFoundError(f"Module not found: {_SRC}")

_spec = importlib.util.spec_from_file_location("skill_gap_analysis_wf", _SRC)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_stemTokens        = _mod._stemTokens
_skillNameTokens   = _mod._skillNameTokens
buildDemandCounter = _mod.buildDemandCounter
scoreDomains       = _mod.scoreDomains
printReport        = _mod.printReport
loadSkillInventory = _mod.loadSkillInventory
loadTaskHistory    = _mod.loadTaskHistory
DOMAIN_MAP         = _mod.DOMAIN_MAP


# ---------------------------------------------------------------------------
# _stemTokens
# ---------------------------------------------------------------------------
class TestStemTokens(unittest.TestCase):
    def test_lowercases_and_splits(self):
        tokens = _stemTokens("Debug Trace ERROR")
        self.assertIn("debug", tokens)
        self.assertIn("trace", tokens)
        self.assertIn("error", tokens)

    def test_truncates_to_10_chars(self):
        tokens = _stemTokens("orchestration")
        self.assertIn("orchestrat", tokens)
        self.assertNotIn("orchestration", tokens)

    def test_ignores_short_words(self):
        tokens = _stemTokens("a ab abc")
        self.assertNotIn("a", tokens)
        self.assertNotIn("ab", tokens)
        self.assertIn("abc", tokens)

    def test_empty_string(self):
        self.assertEqual(_stemTokens(""), [])

    def test_digits_allowed_after_first_char(self):
        tokens = _stemTokens("test123 abc2")
        self.assertIn("test123", tokens)
        self.assertIn("abc2", tokens)

    def test_numbers_only_not_included(self):
        tokens = _stemTokens("123 456")
        self.assertEqual(tokens, [])


# ---------------------------------------------------------------------------
# _skillNameTokens
# ---------------------------------------------------------------------------
class TestSkillNameTokens(unittest.TestCase):
    def test_hyphen_split(self):
        self.assertEqual(_skillNameTokens("skill-gap-analysis"), {"skill", "gap", "analysis"})

    def test_underscore_split(self):
        self.assertEqual(_skillNameTokens("skill_gap_analysis"), {"skill", "gap", "analysis"})

    def test_single_word(self):
        self.assertEqual(_skillNameTokens("testing"), {"testing"})

    def test_lowercases_input(self):
        result = _skillNameTokens("Foo-Bar")
        self.assertIn("foo", result)
        self.assertIn("bar", result)


# ---------------------------------------------------------------------------
# loadSkillInventory
# ---------------------------------------------------------------------------
class TestLoadSkillInventory(unittest.TestCase):
    def test_reads_md_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "testing.md").write_text("pytest coverage assert", encoding="utf-8")
            (d / "debugging.md").write_text("trace inspect replay", encoding="utf-8")
            with patch.object(_mod, "SKILLS_DIR", d):
                inv = loadSkillInventory()
        self.assertIn("testing", inv)
        self.assertIn("debugging", inv)
        self.assertTrue(any("pytest" in t for t in inv["testing"]))

    def test_reads_subdir_skill(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            sub = d / "workflow"
            sub.mkdir()
            (sub / "README.md").write_text("pipeline orchestration schedule", encoding="utf-8")
            with patch.object(_mod, "SKILLS_DIR", d):
                inv = loadSkillInventory()
        self.assertIn("workflow", inv)

    def test_ignores_dotfiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / ".hidden.md").write_text("secret", encoding="utf-8")
            (d / "visible.md").write_text("debug trace", encoding="utf-8")
            with patch.object(_mod, "SKILLS_DIR", d):
                inv = loadSkillInventory()
        self.assertNotIn(".hidden", inv)
        self.assertIn("visible", inv)

    def test_ignores_py_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = pathlib.Path(tmp)
            (d / "helper.py").write_text("# python", encoding="utf-8")
            (d / "real.md").write_text("debug trace", encoding="utf-8")
            with patch.object(_mod, "SKILLS_DIR", d):
                inv = loadSkillInventory()
        self.assertNotIn("helper", inv)
        self.assertIn("real", inv)

    def test_nonexistent_dir_returns_empty(self):
        with patch.object(_mod, "SKILLS_DIR", pathlib.Path("/nonexistent/xyz")):
            inv = loadSkillInventory()
        self.assertEqual(inv, {})

    def test_empty_dir_returns_empty(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(_mod, "SKILLS_DIR", pathlib.Path(tmp)):
                inv = loadSkillInventory()
        self.assertEqual(inv, {})


# ---------------------------------------------------------------------------
# loadTaskHistory — parallel loading (ThreadPoolExecutor)
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

    def test_multiple_tasks_all_loaded_in_parallel(self):
        with tempfile.TemporaryDirectory() as tmp:
            for i in range(8):
                (pathlib.Path(tmp) / f"task-{i:03d}.json").write_text(
                    json.dumps({"meta": {"goal_raw": f"goal {i}"}, "plan": {}})
                )
            with patch.object(_mod, "TASKS_DIR", pathlib.Path(tmp)):
                result = loadTaskHistory()
        self.assertEqual(len(result), 8)

    def test_non_json_files_not_loaded(self):
        with tempfile.TemporaryDirectory() as tmp:
            (pathlib.Path(tmp) / "notes.txt").write_text("ignore me")
            (pathlib.Path(tmp) / "real.json").write_text(json.dumps({"meta": {}}))
            with patch.object(_mod, "TASKS_DIR", pathlib.Path(tmp)):
                result = loadTaskHistory()
        self.assertEqual(len(result), 1)

    def test_parallel_load_returns_same_count_as_files(self):
        """ThreadPoolExecutor must not drop or duplicate task entries."""
        with tempfile.TemporaryDirectory() as tmp:
            count = 20
            for i in range(count):
                (pathlib.Path(tmp) / f"t{i}.json").write_text(
                    json.dumps({"meta": {"goal_raw": f"task {i}"}})
                )
            with patch.object(_mod, "TASKS_DIR", pathlib.Path(tmp)):
                result = loadTaskHistory()
        self.assertEqual(len(result), count)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
        TestStemTokens,
        TestSkillNameTokens,
        TestLoadSkillInventory,
        TestLoadTaskHistory,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
