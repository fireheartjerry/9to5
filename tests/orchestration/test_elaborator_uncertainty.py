import unittest
from agents.planning.elaborator import uncertainty


class TestRiskBand(unittest.TestCase):
    def test_low_only_when_both(self):
        self.assertEqual(uncertainty.riskBand(path_verified=True, precedent_support=True), "low")

    def test_elevated_when_either_missing(self):
        self.assertEqual(uncertainty.riskBand(path_verified=False, precedent_support=True), "elevated")
        self.assertEqual(uncertainty.riskBand(path_verified=True, precedent_support=False), "elevated")


class TestRunUncertainty(unittest.TestCase):
    def test_defer_when_elevated_count_high(self):
        r = uncertainty.runUncertainty(elevated_count=2, objective_spread=0.5, precedent_hits=3)
        self.assertTrue(r["defer"])

    def test_no_defer_when_confident(self):
        r = uncertainty.runUncertainty(elevated_count=0, objective_spread=0.5, precedent_hits=3)
        self.assertFalse(r["defer"])

    def test_defer_when_flat_spread_and_no_precedent(self):
        r = uncertainty.runUncertainty(elevated_count=0, objective_spread=0.01, precedent_hits=0)
        self.assertTrue(r["defer"])
        self.assertTrue(r["reasons"])
