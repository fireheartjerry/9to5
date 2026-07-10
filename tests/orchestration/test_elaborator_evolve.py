import unittest
from unittest import mock
from agents.planning.elaborator import evolve


class TestRecord(unittest.TestCase):
    def test_records_via_store_fn(self):
        seen = {}
        def store(goal, stance, clean_run):
            seen["args"] = (goal, stance, clean_run)
            return True
        self.assertTrue(evolve.recordElaborationOutcome("g", "thorough", clean_run=True, store_fn=store))
        self.assertEqual(seen["args"], ("g", "thorough", True))

    def test_store_error_returns_false(self):
        def boom(*a, **k):
            raise RuntimeError("ledger down")
        self.assertFalse(evolve.recordElaborationOutcome("g", "s", clean_run=False, store_fn=boom))

    def test_rich_outcome_is_forwarded_to_modern_store(self):
        seen = {}
        def store(goal, stance, clean_run, **kw):
            seen.update(goal=goal, stance=stance, clean_run=clean_run, **kw)
            return True
        self.assertTrue(evolve.recordElaborationOutcome(
            "goal", "thorough", clean_run=True, run_id="run-1", spec="# Objective\nGoal",
            metadata={"candidates": {"candidate_count": 3}}, store_fn=store))
        self.assertEqual(seen["run_id"], "run-1")
        self.assertIn("candidate_count", seen["metadata"]["candidates"])

    def test_kill_switch_skips(self):
        called = {"n": 0}
        def store(*a, **k):
            called["n"] += 1
            return True
        with mock.patch.object(__import__("config"), "SIE_KILL_SWITCH", True):
            out = evolve.recordElaborationOutcome("g", "s", clean_run=True, store_fn=store)
        self.assertFalse(out)
        self.assertEqual(called["n"], 0)
