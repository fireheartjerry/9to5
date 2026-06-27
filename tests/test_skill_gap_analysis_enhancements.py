#!/usr/bin/env python3
"""
tests/test_skill_gap_analysis_enhancements.py
Acceptance tests for enhancements in workflows/skill-gap-analysis.py.

Targets behaviors introduced or changed vs .claude/skills/skill-gap-analysis.py:
  1. _loadOneTask: new isolated per-file loader helper
  2. ThreadPoolExecutor parallel loading: correctness, no drops/duplicates
  3. loadSkillInventory: SKILLS_DIR.exists() guard (early return, no exception)
  4. loadSkillInventory: .py exclusion (replaces same-file name check)
  5. scoreDomains: name-only coverage (secondary content matching removed)
  6. Coverage saturation and gap rounding

Run: python C:\\9to5\\tests\\test_skill_gap_analysis_enhancements.py  (exits 0 on pass)
"""
import importlib.util
import io
import json
import pathlib
import sys
import tempfile
import unittest
from collections import Counter
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Load workflow module under test
# ---------------------------------------------------------------------------
_SRC = pathlib.Path("C:/9to5/workflows/skill-gap-analysis.py")
if not _SRC.exists():
    raise FileNotFoundError(f"Workflow module not found: {_SRC}")

_spec = importlib.util.spec_from_file_location("skill_gap_analysis_wf_enh", _SRC)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_loadOneTask       = _mod._loadOneTask
loadTaskHistory    = _mod.loadTaskHistory
loadSkillInventory = _mod.loadSkillInventory
scoreDomains       = _mod.scoreDomains
DOMAIN_MAP         = _mod.DOMAIN_MAP


# ---------------------------------------------------------------------------
# Enhancement 1: _loadOneTask helper
# ---------------------------------------------------------------------------
class TestLoadOneTask(unittest.TestCase):
    """_loadOneTask is a new isolated helper absent from the original skill script."""

    def test_returns_dict_for_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "task.json"
            data = {"meta": {"goal_raw": "test"}, "plan": {}}
            p.write_text(json.dumps(data), encoding="utf-8")
            result = _loadOneTask(p)
        self.assertEqual(result, data)

    def test_returns_none_for_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "bad.json"
            p.write_text("{ not valid !!!", encoding="utf-8")
            with patch("sys.stderr", new_callable=io.StringIO):
                result = _loadOneTask(p)
        self.assertIsNone(result)

    def test_writes_warn_to_stderr_on_bad_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "bad.json"
            p.write_text("not-json", encoding="utf-8")
            buf = io.StringIO()
            with patch("sys.stderr", buf):
                _loadOneTask(p)
        self.assertIn("warn", buf.getvalue().lower())

    def test_returns_none_for_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "empty.json"
            p.write_text("", encoding="utf-8")
            with patch("sys.stderr", new_callable=io.StringIO):
                result = _loadOneTask(p)
        self.assertIsNone(result)

    def test_returns_none_for_nonexistent_file(self):
        p = pathlib.Path("/nonexistent/path/task.json")
        with patch("sys.stderr", new_callable=io.StringIO):
            result = _loadOneTask(p)
        self.assertIsNone(result)

    def test_preserves_nested_structure(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "task.json"
            data = {
                "meta": {"goal_raw": "deploy", "goal_elaborated": "deploy to prod"},
                "plan": {"subtasks": [{"title": "build", "description": "build it"}]},
            }
            p.write_text(json.dumps(data), encoding="utf-8")
            result = _loadOneTask(p)
        self.assertEqual(result["plan"]["subtasks"][0]["title"], "build")


# ---------------------------------------------------------------------------
# Enhancement 2: ThreadPoolExecutor parallel loading correctness
# ---------------------------------------------------------------------------
class TestParallelLoadTaskHistory(unittest.TestCase):
    """Parallel loading must not drop or duplicate tasks."""

    def test_no_drops_with_many_files(self):
        count = 24
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            for i in range(count):
                (tp / f"t{i:03d}.json").write_text(
                    json.dumps({"meta": {"goal_raw": f"task {i}"}}),
                    encoding="utf-8",
                )
            with patch.object(_mod, "TASKS_DIR", tp):
                result = loadTaskHistory()
        self.assertEqual(len(result), count)

    def test_no_duplicates_with_many_files(self):
        count = 16
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            for i in range(count):
                (tp / f"t{i:03d}.json").write_text(
                    json.dumps({"meta": {"goal_raw": f"unique-goal-{i}"}}),
                    encoding="utf-8",
                )
            with patch.object(_mod, "TASKS_DIR", tp):
                result = loadTaskHistory()
        goals = [r["meta"]["goal_raw"] for r in result]
        self.assertEqual(len(goals), len(set(goals)))

    def test_valid_tasks_returned_despite_some_invalid(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            # 3 valid, 2 invalid
            for i in range(3):
                (tp / f"good{i}.json").write_text(
                    json.dumps({"meta": {"goal_raw": f"goal {i}"}}), encoding="utf-8"
                )
            (tp / "bad1.json").write_text("not-json", encoding="utf-8")
            (tp / "bad2.json").write_text("{broken", encoding="utf-8")
            with patch.object(_mod, "TASKS_DIR", tp):
                with patch("sys.stderr", new_callable=io.StringIO):
                    result = loadTaskHistory()
        self.assertEqual(len(result), 3)

    def test_empty_dir_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(_mod, "TASKS_DIR", pathlib.Path(tmp)):
                result = loadTaskHistory()
        self.assertEqual(result, [])

    def test_all_invalid_returns_empty_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            for i in range(4):
                (tp / f"bad{i}.json").write_text("INVALID", encoding="utf-8")
            with patch.object(_mod, "TASKS_DIR", tp):
                with patch("sys.stderr", new_callable=io.StringIO):
                    result = loadTaskHistory()
        self.assertEqual(result, [])

    def test_non_json_files_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            (tp / "notes.txt").write_text("ignore me", encoding="utf-8")
            (tp / "data.csv").write_text("a,b,c", encoding="utf-8")
            (tp / "real.json").write_text(json.dumps({"meta": {}}), encoding="utf-8")
            with patch.object(_mod, "TASKS_DIR", tp):
                result = loadTaskHistory()
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# Enhancement 3: SKILLS_DIR.exists() guard
# ---------------------------------------------------------------------------
class TestSkillsDirExistsGuard(unittest.TestCase):
    """Workflow adds an early-return guard for nonexistent SKILLS_DIR."""

    def test_nonexistent_dir_returns_empty_dict(self):
        with patch.object(_mod, "SKILLS_DIR", pathlib.Path("/totally/nonexistent/xyz")):
            result = loadSkillInventory()
        self.assertEqual(result, {})

    def test_nonexistent_dir_does_not_raise(self):
        with patch.object(_mod, "SKILLS_DIR", pathlib.Path("/no/such/path")):
            try:
                loadSkillInventory()
            except Exception as exc:
                self.fail(f"loadSkillInventory raised unexpectedly: {exc}")


# ---------------------------------------------------------------------------
# Enhancement 4: .py file exclusion from skill inventory
# ---------------------------------------------------------------------------
class TestPyFileExclusion(unittest.TestCase):
    """Workflow excludes .py files from inventory (original excluded only self-file)."""

    def test_py_files_not_added_as_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / "helper.py").write_text("# some python", encoding="utf-8")
            (p / "runner.py").write_text("import sys", encoding="utf-8")
            with patch.object(_mod, "SKILLS_DIR", p):
                inv = loadSkillInventory()
        self.assertNotIn("helper", inv)
        self.assertNotIn("runner", inv)

    def test_md_files_still_added(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / "helper.py").write_text("# python", encoding="utf-8")
            (p / "debugging.md").write_text("trace inspect replay", encoding="utf-8")
            with patch.object(_mod, "SKILLS_DIR", p):
                inv = loadSkillInventory()
        self.assertIn("debugging", inv)
        self.assertNotIn("helper", inv)

    def test_dotfiles_still_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / ".hidden").write_text("secret", encoding="utf-8")
            (p / ".hidden.md").write_text("secret2", encoding="utf-8")
            (p / "visible.md").write_text("debug trace", encoding="utf-8")
            with patch.object(_mod, "SKILLS_DIR", p):
                inv = loadSkillInventory()
        self.assertIn("visible", inv)
        self.assertNotIn(".hidden", inv)

    def test_subdir_skills_still_included(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            skill_sub = p / "workflow-patterns"
            skill_sub.mkdir()
            (skill_sub / "skill.md").write_text("pipeline orchestration")
            with patch.object(_mod, "SKILLS_DIR", p):
                inv = loadSkillInventory()
        self.assertIn("workflow-patterns", inv)


# ---------------------------------------------------------------------------
# Enhancement 5: scoreDomains name-only coverage
# ---------------------------------------------------------------------------
class TestNameOnlyCoverage(unittest.TestCase):
    """Workflow scoreDomains matches by skill NAME only — not content tokens."""

    def test_skill_matched_by_name_prefix(self):
        demand = Counter({"test": 8})
        inventory = {"test-automation": set()}
        rows = scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        self.assertIn("test-automation", testing_row["covered_by"])

    def test_skill_not_matched_by_content_only(self):
        # Skill named "generic-skill" with content tokens about testing.
        # Workflow does NOT use content tokens for coverage — name-only.
        demand = Counter({"test": 10})
        content_tokens = {"test", "pytest", "coverage", "assert", "validate"}
        inventory = {"generic-skill": content_tokens}
        rows = scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        # name "generic-skill" has no testing-related prefix → not covered
        self.assertNotIn("generic-skill", testing_row["covered_by"])

    def test_unrelated_skill_does_not_reduce_gap(self):
        demand = Counter({"deploy": 6})
        inventory = {"memory-helper": set()}  # unrelated name
        rows = scoreDomains(demand, inventory)
        deploy_row = next(r for r in rows if r["domain"] == "deployment")
        self.assertEqual(deploy_row["gap_score"], 6.0)
        self.assertNotIn("memory-helper", deploy_row["covered_by"])

    def test_gap_score_rounding_to_two_decimals(self):
        demand = Counter({"test": 3})  # 3 demand, 1 skill → gap = 3 * 0.5 = 1.5
        inventory = {"test-helper": set()}
        rows = scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        self.assertEqual(testing_row["gap_score"], 1.5)
        self.assertIsInstance(testing_row["gap_score"], float)

    def test_three_skills_saturate_at_two(self):
        demand = Counter({"test": 12})
        inventory = {"test-a": set(), "test-b": set(), "test-c": set()}
        rows = scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        # coverage = min(3, 2) / 2 = 1.0 → gap = 0
        self.assertEqual(testing_row["gap_score"], 0.0)

    def test_all_domains_have_required_keys(self):
        rows = scoreDomains(Counter(), {})
        for row in rows:
            self.assertIn("domain", row)
            self.assertIn("demand", row)
            self.assertIn("covered_by", row)
            self.assertIn("gap_score", row)
            self.assertIsInstance(row["covered_by"], list)

    def test_sorted_descending_gap(self):
        demand = Counter({"test": 50, "deploy": 5, "debug": 20})
        rows = scoreDomains(demand, {})
        scores = [r["gap_score"] for r in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_zero_demand_zero_gap_regardless_of_inventory(self):
        inventory = {"test-helper": set(), "debug-master": set()}
        rows = scoreDomains(Counter(), inventory)
        for row in rows:
            self.assertEqual(row["gap_score"], 0.0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
        TestLoadOneTask,
        TestParallelLoadTaskHistory,
        TestSkillsDirExistsGuard,
        TestPyFileExclusion,
        TestNameOnlyCoverage,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
