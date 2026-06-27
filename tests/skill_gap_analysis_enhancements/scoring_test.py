#!/usr/bin/env python3
"""
tests/skill_gap_analysis_enhancements/scoring_test.py
Tests for Enhancement 5 (name-only coverage) and Enhancement 6 (saturation + rounding).
"""
import importlib.util
import pathlib
import unittest
from collections import Counter

_SRC = pathlib.Path("C:/9to5/workflows/skill-gap-analysis.py")
_spec = importlib.util.spec_from_file_location("_sga_wf_scoring", _SRC)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

scoreDomains = _mod.scoreDomains
DOMAIN_MAP = _mod.DOMAIN_MAP


class TestNameOnlyCoverage(unittest.TestCase):
    """Enhancement 5: scoreDomains matches by skill NAME only — content tokens not used."""

    def test_skill_matched_by_name_prefix(self):
        demand = Counter({"test": 8})
        inventory = {"test-automation": set()}
        rows = scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        self.assertIn("test-automation", testing_row["covered_by"])

    def test_content_only_skill_not_matched(self):
        # Skill name "generic-util" has no testing keywords in name.
        # Even if content_tokens has testing words, name-only matching ignores them.
        demand = Counter({"test": 10})
        inventory = {"generic-util": {"test", "pytest", "coverage", "assert"}}
        rows = scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        self.assertNotIn("generic-util", testing_row["covered_by"])

    def test_unrelated_skill_does_not_reduce_gap(self):
        demand = Counter({"deploy": 6})
        inventory = {"memory-helper": set()}
        rows = scoreDomains(demand, inventory)
        deploy_row = next(r for r in rows if r["domain"] == "deployment")
        self.assertEqual(deploy_row["gap_score"], 6.0)
        self.assertNotIn("memory-helper", deploy_row["covered_by"])

    def test_skill_name_split_on_hyphen(self):
        demand = Counter({"debug": 5})
        inventory = {"systematic-debugging": set()}
        rows = scoreDomains(demand, inventory)
        debug_row = next(r for r in rows if r["domain"] == "debugging")
        self.assertIn("systematic-debugging", debug_row["covered_by"])

    def test_skill_name_split_on_underscore(self):
        demand = Counter({"monitor": 4})
        inventory = {"health_monitor": set()}
        rows = scoreDomains(demand, inventory)
        monitor_row = next(r for r in rows if r["domain"] == "monitoring")
        self.assertIn("health_monitor", monitor_row["covered_by"])


class TestSaturationAndRounding(unittest.TestCase):
    """Enhancement 6: coverage saturates at 2 skills; gap rounded to 2 decimal places."""

    def test_one_skill_partial_coverage(self):
        demand = Counter({"test": 4})
        inventory = {"test-helper": set()}
        rows = scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        # 1 skill / 2 sat = 50% → gap = 4 * 0.5 = 2.0
        self.assertEqual(testing_row["gap_score"], 2.0)

    def test_two_skills_full_coverage(self):
        demand = Counter({"test": 10})
        inventory = {"test-a": set(), "test-b": set()}
        rows = scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        self.assertEqual(testing_row["gap_score"], 0.0)

    def test_three_skills_still_saturated(self):
        demand = Counter({"test": 12})
        inventory = {"test-a": set(), "test-b": set(), "test-c": set()}
        rows = scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        self.assertEqual(testing_row["gap_score"], 0.0)

    def test_gap_score_is_float(self):
        demand = Counter({"test": 3})
        inventory = {"test-helper": set()}
        rows = scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        self.assertIsInstance(testing_row["gap_score"], float)

    def test_gap_score_rounded_to_two_decimals(self):
        demand = Counter({"test": 3})
        inventory = {"test-helper": set()}
        rows = scoreDomains(demand, inventory)
        testing_row = next(r for r in rows if r["domain"] == "testing")
        self.assertEqual(testing_row["gap_score"], round(testing_row["gap_score"], 2))

    def test_zero_demand_zero_gap(self):
        rows = scoreDomains(Counter(), {"test-helper": set(), "debug-master": set()})
        for row in rows:
            self.assertEqual(row["gap_score"], 0.0)

    def test_sorted_descending_by_gap(self):
        demand = Counter({"test": 50, "deploy": 3, "debug": 20})
        rows = scoreDomains(demand, {})
        scores = [r["gap_score"] for r in rows]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_all_rows_have_required_keys(self):
        rows = scoreDomains(Counter(), {})
        required = {"domain", "demand", "covered_by", "gap_score"}
        for row in rows:
            self.assertTrue(required.issubset(row.keys()))
            self.assertIsInstance(row["covered_by"], list)

    def test_all_domains_present_in_output(self):
        rows = scoreDomains(Counter(), {})
        output_domains = {r["domain"] for r in rows}
        self.assertEqual(output_domains, set(DOMAIN_MAP.keys()))


if __name__ == "__main__":
    unittest.main()
