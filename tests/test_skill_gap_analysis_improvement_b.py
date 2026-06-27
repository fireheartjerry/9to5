#!/usr/bin/env python3
"""
tests/test_skill_gap_analysis_improvement_b.py
Regression tests for skill-gap-analysis improvements — Part B.

Covers:
  6. SKILLS_DIR.exists() guard: no exception on missing dir.
  7. .py file exclusion from inventory (simpler rule).
  8. scoreDomains: name-only coverage matching (no secondary content).
  9. main() integration regression.

Split from test_skill_gap_analysis_improvement.py (was 395 lines).
Run: python -m pytest tests/test_skill_gap_analysis_improvement_b.py
"""
import importlib.util
import io
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
        TestSkillsDirGuard,
        TestPyFileExclusion,
        TestNameOnlyCoverage,
        TestMainRegression,
    ]:
        suite.addTests(loader.loadTestsFromTestCase(cls))

    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    sys.exit(0 if result.wasSuccessful() else 1)
