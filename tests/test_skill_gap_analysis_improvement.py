#!/usr/bin/env python3
"""
tests/test_skill_gap_analysis_improvement.py
Regression tests for skill-gap-analysis improvements — merged.

Covers:
  Part A:
  1. _stemTokens: identical output from original and workflow modules.
  2. buildDemandCounter: identical output from both modules.
  3. DOMAIN_MAP: workflow covers every domain the original declares.
  4. _loadOneTask: new per-file loader helper.
  5. Parallel loading via ThreadPoolExecutor: no drops or duplicates.

  Part B:
  6. SKILLS_DIR.exists() guard: no exception on missing dir.
  7. .py file exclusion from inventory (simpler rule).
  8. scoreDomains: name-only coverage matching (no secondary content).
  9. main() integration regression.
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
# Load both modules for cross-comparison
# ---------------------------------------------------------------------------
_ORIG_SRC = pathlib.Path("C:/9to5/.claude/skills/skill-gap-analysis.py")
_WF_SRC   = pathlib.Path("C:/9to5/workflows/skill-gap-analysis.py")

for _p in (_ORIG_SRC, _WF_SRC):
    if not _p.exists():
        raise FileNotFoundError(f"Required module not found: {_p}")

_orig_spec = importlib.util.spec_from_file_location("sga_orig", _ORIG_SRC)
_orig = importlib.util.module_from_spec(_orig_spec)
_orig_spec.loader.exec_module(_orig)

_wf_spec = importlib.util.spec_from_file_location("sga_wf", _WF_SRC)
_wf = importlib.util.module_from_spec(_wf_spec)
_wf_spec.loader.exec_module(_wf)


# ---------------------------------------------------------------------------
# 1. _stemTokens — must be identical in both modules
# ---------------------------------------------------------------------------
class TestStemTokensRegression(unittest.TestCase):
    _CASES = [
        ("Deploy Release Artifact", ["deploy", "release", "artifact"]),
        ("orchestration", ["orchestrat"]),
        ("a ab abc test", ["abc", "test"]),
        ("", []),
        ("test123 abc2", ["test123", "abc2"]),
        ("123 456 789", []),
    ]

    def test_orig_and_wf_produce_identical_results(self):
        for text, _ in self._CASES:
            orig_out = _orig._stemTokens(text)
            wf_out   = _wf._stemTokens(text)
            self.assertEqual(
                sorted(orig_out), sorted(wf_out),
                f"_stemTokens diverged for {text!r}: orig={orig_out} wf={wf_out}",
            )

    def test_truncates_to_10_chars(self):
        self.assertIn("orchestrat", _wf._stemTokens("orchestration"))
        self.assertNotIn("orchestration", _wf._stemTokens("orchestration"))

    def test_min_length_3(self):
        tokens = _wf._stemTokens("a ab abc")
        self.assertNotIn("a", tokens)
        self.assertNotIn("ab", tokens)
        self.assertIn("abc", tokens)


# ---------------------------------------------------------------------------
# 2. buildDemandCounter — must be identical in both modules
# ---------------------------------------------------------------------------
class TestBuildDemandCounterRegression(unittest.TestCase):
    _TASKS = [
        {"meta": {"goal_raw": "deploy service", "goal_elaborated": "deploy to prod"},
         "plan": {"subtasks": [{"title": "write tests", "description": "pytest"}]}},
        {"meta": {"goal_raw": "debug failing test"}, "plan": {}},
        {},
    ]

    def test_same_output_both_modules(self):
        orig_counter = _orig.buildDemandCounter(self._TASKS)
        wf_counter   = _wf.buildDemandCounter(self._TASKS)
        self.assertEqual(dict(orig_counter), dict(wf_counter))

    def test_empty_input_returns_empty_counter(self):
        counter = _wf.buildDemandCounter([])
        self.assertEqual(len(counter), 0)

    def test_accumulates_across_tasks(self):
        tasks = [
            {"meta": {"goal_raw": "debug issue"}, "plan": {}},
            {"meta": {"goal_raw": "debug logs"},  "plan": {}},
        ]
        counter = _wf.buildDemandCounter(tasks)
        self.assertGreaterEqual(counter["debug"], 2)

    def test_missing_keys_tolerated(self):
        tasks = [{"meta": {}}, {}, {"plan": {}}]
        counter = _wf.buildDemandCounter(tasks)
        self.assertIsInstance(counter, Counter)


# ---------------------------------------------------------------------------
# 3. DOMAIN_MAP — workflow must cover every domain the original declares
# ---------------------------------------------------------------------------
class TestDomainMapRegression(unittest.TestCase):
    def test_wf_has_all_original_domains(self):
        missing = set(_orig.DOMAIN_MAP.keys()) - set(_wf.DOMAIN_MAP.keys())
        self.assertEqual(missing, set(), f"Workflow missing domains: {missing}")

    def test_no_empty_keyword_sets(self):
        for domain, kws in _wf.DOMAIN_MAP.items():
            self.assertGreater(len(kws), 0, f"Domain '{domain}' has no keywords")


# ---------------------------------------------------------------------------
# 4. _loadOneTask — new helper present only in workflow module
# ---------------------------------------------------------------------------
class TestLoadOneTask(unittest.TestCase):
    def test_present_in_workflow_module(self):
        self.assertTrue(hasattr(_wf, "_loadOneTask"), "_loadOneTask missing from workflow module")

    def test_returns_dict_for_valid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "task.json"
            data = {"meta": {"goal_raw": "test goal"}, "plan": {}}
            p.write_text(json.dumps(data), encoding="utf-8")
            result = _wf._loadOneTask(p)
        self.assertEqual(result, data)

    def test_returns_none_for_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "bad.json"
            p.write_text("{ not valid !!!", encoding="utf-8")
            with patch("sys.stderr", new_callable=io.StringIO):
                result = _wf._loadOneTask(p)
        self.assertIsNone(result)

    def test_emits_warn_to_stderr_on_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "bad.json"
            p.write_text("not-json", encoding="utf-8")
            buf = io.StringIO()
            with patch("sys.stderr", buf):
                _wf._loadOneTask(p)
        self.assertIn("warn", buf.getvalue().lower())

    def test_returns_none_for_empty_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp) / "empty.json"
            p.write_text("", encoding="utf-8")
            with patch("sys.stderr", new_callable=io.StringIO):
                result = _wf._loadOneTask(p)
        self.assertIsNone(result)


# ---------------------------------------------------------------------------
# 5. Parallel loading — no drops, no duplicates
# ---------------------------------------------------------------------------
class TestParallelLoading(unittest.TestCase):
    def test_no_drops_with_many_files(self):
        count = 24
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            for i in range(count):
                (tp / f"t{i:03d}.json").write_text(
                    json.dumps({"meta": {"goal_raw": f"task {i}"}}),
                    encoding="utf-8",
                )
            with patch.object(_wf, "TASKS_DIR", tp):
                result = _wf.loadTaskHistory()
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
            with patch.object(_wf, "TASKS_DIR", tp):
                result = _wf.loadTaskHistory()
        goals = [r["meta"]["goal_raw"] for r in result]
        self.assertEqual(len(goals), len(set(goals)))

    def test_valid_tasks_returned_despite_invalid_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            for i in range(3):
                (tp / f"good{i}.json").write_text(
                    json.dumps({"meta": {"goal_raw": f"goal {i}"}}), encoding="utf-8"
                )
            (tp / "bad1.json").write_text("not-json", encoding="utf-8")
            (tp / "bad2.json").write_text("{broken", encoding="utf-8")
            with patch.object(_wf, "TASKS_DIR", tp):
                with patch("sys.stderr", new_callable=io.StringIO):
                    result = _wf.loadTaskHistory()
        self.assertEqual(len(result), 3)

    def test_nonexistent_tasks_dir_returns_empty(self):
        with patch.object(_wf, "TASKS_DIR", pathlib.Path("/totally/nonexistent/xyz")):
            result = _wf.loadTaskHistory()
        self.assertEqual(result, [])

    def test_non_json_files_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            tp = pathlib.Path(tmp)
            (tp / "notes.txt").write_text("ignore me", encoding="utf-8")
            (tp / "real.json").write_text(json.dumps({"meta": {}}), encoding="utf-8")
            with patch.object(_wf, "TASKS_DIR", tp):
                result = _wf.loadTaskHistory()
        self.assertEqual(len(result), 1)


# ---------------------------------------------------------------------------
# 6. SKILLS_DIR.exists() guard
# ---------------------------------------------------------------------------
class TestSkillsDirGuard(unittest.TestCase):
    def test_nonexistent_dir_returns_empty_dict(self):
        with patch.object(_wf, "SKILLS_DIR", pathlib.Path("/totally/nonexistent/abc")):
            result = _wf.loadSkillInventory()
        self.assertEqual(result, {})

    def test_nonexistent_dir_does_not_raise(self):
        with patch.object(_wf, "SKILLS_DIR", pathlib.Path("/no/such/path/xyz")):
            try:
                _wf.loadSkillInventory()
            except Exception as exc:
                self.fail(f"loadSkillInventory raised on missing dir: {exc}")


# ---------------------------------------------------------------------------
# 7. .py exclusion from inventory
# ---------------------------------------------------------------------------
class TestPyFileExclusion(unittest.TestCase):
    def test_py_files_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / "helper.py").write_text("# python code", encoding="utf-8")
            (p / "runner.py").write_text("import sys", encoding="utf-8")
            with patch.object(_wf, "SKILLS_DIR", p):
                inv = _wf.loadSkillInventory()
        self.assertNotIn("helper", inv)
        self.assertNotIn("runner", inv)

    def test_md_files_included_alongside_py_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / "helper.py").write_text("# python", encoding="utf-8")
            (p / "debugging.md").write_text("trace inspect replay", encoding="utf-8")
            with patch.object(_wf, "SKILLS_DIR", p):
                inv = _wf.loadSkillInventory()
        self.assertIn("debugging", inv)
        self.assertNotIn("helper", inv)

    def test_dotfiles_still_excluded(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / ".hidden.md").write_text("secret", encoding="utf-8")
            (p / "visible.md").write_text("debug trace", encoding="utf-8")
            with patch.object(_wf, "SKILLS_DIR", p):
                inv = _wf.loadSkillInventory()
        self.assertNotIn(".hidden", inv)
        self.assertIn("visible", inv)


# ---------------------------------------------------------------------------
# 8. scoreDomains: name-only coverage (no secondary content matching)
# ---------------------------------------------------------------------------
class TestNameOnlyCoverage(unittest.TestCase):
    def test_skill_matched_by_name_prefix(self):
        demand = Counter({"test": 8})
        inventory = {"test-automation": set()}
        rows = _wf.scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        self.assertIn("test-automation", testing_row["covered_by"])

    def test_skill_not_matched_by_content_only(self):
        demand = Counter({"test": 10})
        # Content has testing keywords but name is unrelated
        content_tokens = {"test", "pytest", "coverage", "assert", "validate"}
        inventory = {"generic-skill": content_tokens}
        rows = _wf.scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        # Name "generic-skill" has no testing-related prefix → should not cover
        self.assertNotIn("generic-skill", testing_row["covered_by"])

    def test_unrelated_skill_does_not_reduce_gap(self):
        demand = Counter({"deploy": 6})
        inventory = {"memory-helper": set()}
        rows = _wf.scoreDomains(demand, inventory)
        deploy_row = next(r for r in rows if r["domain"] == "deployment")
        self.assertEqual(deploy_row["gap_score"], 6.0)
        self.assertNotIn("memory-helper", deploy_row["covered_by"])

    def test_three_skills_saturate_at_two(self):
        demand = Counter({"test": 12})
        inventory = {"test-a": set(), "test-b": set(), "test-c": set()}
        rows = _wf.scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        # coverage = min(3, 2) / 2 = 1.0 → gap = 0
        self.assertEqual(testing_row["gap_score"], 0.0)

    def test_gap_rounding_two_decimals(self):
        demand = Counter({"test": 3})
        inventory = {"test-helper": set()}
        rows = _wf.scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        # 1 skill out of 2 → 0.5 coverage → gap = 3 * 0.5 = 1.5
        self.assertEqual(testing_row["gap_score"], 1.5)

    def test_sorted_descending_by_gap(self):
        demand = Counter({"test": 100, "deploy": 1})
        rows = _wf.scoreDomains(demand, {})
        scores = [r["gap_score"] for r in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_all_domains_returned(self):
        rows = _wf.scoreDomains(Counter(), {})
        domains = {r["domain"] for r in rows}
        self.assertEqual(domains, set(_wf.DOMAIN_MAP.keys()))

    def test_row_keys_complete(self):
        rows = _wf.scoreDomains(Counter(), {})
        for row in rows:
            for key in ("domain", "demand", "covered_by", "gap_score"):
                self.assertIn(key, row)
            self.assertIsInstance(row["covered_by"], list)


# ---------------------------------------------------------------------------
# 9. main() integration
# ---------------------------------------------------------------------------
class TestMainRegression(unittest.TestCase):
    def test_exits_zero_with_valid_skills_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = pathlib.Path(tmp)
            (p / "debugging.md").write_text("debug trace replay inspect")
            with patch.object(_wf, "SKILLS_DIR", p):
                with patch.object(_wf, "TASKS_DIR", pathlib.Path("/nonexistent/xyz")):
                    with patch("sys.stdout", io.StringIO()):
                        result = _wf.main()
        self.assertEqual(result, 0)

    def test_exits_one_when_no_skills(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(_wf, "SKILLS_DIR", pathlib.Path(tmp)):
                with patch("sys.stderr", io.StringIO()):
                    result = _wf.main()
        self.assertEqual(result, 1)

    def test_exits_zero_with_real_skills_dir(self):
        """Smoke test against live skills directory."""
        with patch("sys.stdout", io.StringIO()):
            result = _wf.main()
        self.assertEqual(result, 0)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for cls in [
        TestStemTokensRegression,
        TestBuildDemandCounterRegression,
        TestDomainMapRegression,
        TestLoadOneTask,
        TestParallelLoading,
        TestSkillsDirGuard,
        TestPyFileExclusion,
        TestNameOnlyCoverage,
        TestMainRegression,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
