#!/usr/bin/env python3
"""
tests/test_skill_gap_analysis_workflow_analysis.py
Acceptance tests for skill-gap-analysis workflow — demand/scoring/reporting/main layer.

Validates:
  - buildDemandCounter accumulates task demand correctly.
  - scoreDomains produces correct gap scores and coverage info.
  - printReport produces expected output sections.
  - main() returns appropriate exit codes.

Split from test_skill_gap_analysis_workflow.py (was 430 lines).
Run: python -m pytest tests/test_skill_gap_analysis_workflow_analysis.py
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
        TestBuildDemandCounter,
        TestScoreDomains,
        TestPrintReport,
        TestMain,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
