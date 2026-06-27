#!/usr/bin/env python3
"""
tests/test_skill_gap_analysis_improvement_a.py
Regression tests for skill-gap-analysis improvements — Part A.

Covers:
  1. _stemTokens: identical output from original and workflow modules.
  2. buildDemandCounter: identical output from both modules.
  3. DOMAIN_MAP: workflow covers every domain the original declares.
  4. _loadOneTask: new per-file loader helper.
  5. Parallel loading via ThreadPoolExecutor: no drops or duplicates.

Split from test_skill_gap_analysis_improvement.py (was 395 lines).
Run: python -m pytest tests/test_skill_gap_analysis_improvement_a.py
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
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
