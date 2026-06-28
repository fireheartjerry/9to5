#!/usr/bin/env python3
"""
tests/test_skill_gap_analysis_workflow.py
Acceptance tests for skill-gap-analysis workflow — merged.

Covers:
  Token/inventory/task-loading layer:
  - _stemTokens and _skillNameTokens produce correct results.
  - loadSkillInventory skips .py / dotfiles / hidden entries.
  - loadTaskHistory (parallel loading via ThreadPoolExecutor) works correctly.

  Demand/scoring/reporting/main layer:
  - buildDemandCounter accumulates task demand correctly.
  - scoreDomains produces correct gap scores and coverage info.
  - printReport produces expected output sections.
  - main() returns appropriate exit codes.
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
# buildDemandCounter
# ---------------------------------------------------------------------------
class TestBuildDemandCounter(unittest.TestCase):
    def test_empty_tasks(self):
        counter = buildDemandCounter([])
        self.assertIsInstance(counter, Counter)
        self.assertEqual(len(counter), 0)

    def test_goal_raw_counted(self):
        tasks = [{"meta": {"goal_raw": "debug this failure"}, "plan": {}}]
        counter = buildDemandCounter(tasks)
        self.assertIn("debug", counter)
        self.assertGreater(counter["debug"], 0)

    def test_goal_elaborated_counted(self):
        tasks = [{"meta": {"goal_elaborated": "test coverage"}, "plan": {}}]
        counter = buildDemandCounter(tasks)
        self.assertIn("test", counter)

    def test_subtask_title_and_desc_counted(self):
        tasks = [{
            "meta": {},
            "plan": {"subtasks": [{"title": "deploy artifact", "description": "release build"}]}
        }]
        counter = buildDemandCounter(tasks)
        self.assertIn("deploy", counter)
        self.assertIn("artifact", counter)
        self.assertIn("release", counter)

    def test_missing_keys_tolerated(self):
        counter = buildDemandCounter([{}, {"meta": {}}, {"plan": {}}])
        self.assertIsInstance(counter, Counter)

    def test_multiple_tasks_accumulate(self):
        tasks = [
            {"meta": {"goal_raw": "test foo"}, "plan": {}},
            {"meta": {"goal_raw": "test bar"}, "plan": {}},
        ]
        counter = buildDemandCounter(tasks)
        self.assertEqual(counter["test"], 2)


# ---------------------------------------------------------------------------
# scoreDomains
# ---------------------------------------------------------------------------
class TestScoreDomains(unittest.TestCase):
    def test_all_domains_present(self):
        rows = scoreDomains(Counter(), {})
        domains = {r["domain"] for r in rows}
        self.assertEqual(domains, set(DOMAIN_MAP.keys()))

    def test_no_demand_no_gap(self):
        rows = scoreDomains(Counter(), {})
        for row in rows:
            self.assertEqual(row["gap_score"], 0.0)

    def test_demand_with_no_coverage_equals_full_gap(self):
        demand = Counter({"test": 5, "testing": 3})
        rows = scoreDomains(demand, {})
        testing_row = next(r for r in rows if r["domain"] == "testing")
        self.assertEqual(testing_row["demand"], 8)
        self.assertEqual(testing_row["gap_score"], 8.0)

    def test_one_covering_skill_halves_gap(self):
        demand = Counter({"test": 4})
        inventory = {"test-automation": set()}
        rows = scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        self.assertEqual(testing_row["gap_score"], 2.0)
        self.assertIn("test-automation", testing_row["covered_by"])

    def test_two_covering_skills_zeroes_gap(self):
        demand = Counter({"test": 10})
        inventory = {"test-runner": set(), "pytest-helper": set()}
        rows = scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        self.assertEqual(testing_row["gap_score"], 0.0)

    def test_sorted_descending_by_gap(self):
        demand = Counter({"test": 10, "deploy": 1})
        rows = scoreDomains(demand, {})
        scores = [r["gap_score"] for r in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_prefix_matching(self):
        demand = Counter({"diagnose": 3})
        rows = scoreDomains(demand, {})
        debug_row = next(r for r in rows if r["domain"] == "debugging")
        self.assertGreater(debug_row["demand"], 0)


# ---------------------------------------------------------------------------
# printReport
# ---------------------------------------------------------------------------
class TestPrintReport(unittest.TestCase):
    def _make_rows(self):
        return [
            {"domain": "testing",  "demand": 10, "covered_by": ["test-helper"], "gap_score": 5.0},
            {"domain": "security", "demand": 8,  "covered_by": [],              "gap_score": 8.0},
            {"domain": "memory",   "demand": 0,  "covered_by": [],              "gap_score": 0.0},
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

    def test_no_critical_section_when_all_covered(self):
        rows = [{"domain": "testing", "demand": 5, "covered_by": ["a", "b"], "gap_score": 0.0}]
        out = self._capture(rows, {"a": set(), "b": set()}, 1)
        self.assertNotIn("Critical Gaps", out)

    def test_truncates_long_coverage_label(self):
        long_skills = ["skill_a", "skill_b", "skill_c", "skill_d", "skill_e", "skill_f"]
        rows = [{"domain": "testing", "demand": 1, "covered_by": long_skills, "gap_score": 0.0}]
        out = self._capture(rows, {}, 1)
        self.assertIn("...", out)


# ---------------------------------------------------------------------------
# main() integration
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

    def test_real_skills_dir_produces_exit_zero(self):
        """Smoke test against the live skills directory."""
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
        TestStemTokens,
        TestSkillNameTokens,
        TestLoadSkillInventory,
        TestLoadTaskHistory,
        TestBuildDemandCounter,
        TestScoreDomains,
        TestPrintReport,
        TestMain,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
