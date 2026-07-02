"""Unit tests for the eval-harness fitness math + suite loading (SIE spine)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from learning import eval_harness as eh


class TestFitnessMath(unittest.TestCase):
    def test_perfect_metrics_score_one(self):
        perfect = {"first_pass_rate": 1.0, "norm_attempts": 0.0, "norm_cost": 0.0,
                   "plan_stability": 1.0, "challenge_rate": 0.0}
        self.assertEqual(eh.compute_fitness(perfect), 1.0)

    def test_worst_metrics_score_zero(self):
        worst = {"first_pass_rate": 0.0, "norm_attempts": 1.0, "norm_cost": 1.0,
                 "plan_stability": 0.0, "challenge_rate": 1.0}
        self.assertEqual(eh.compute_fitness(worst), 0.0)

    def test_weights_sum_makes_bounds_meaningful(self):
        self.assertAlmostEqual(sum(config.EVAL_FITNESS_WEIGHTS.values()), 1.0, places=6)

    def test_fitness_is_clipped_and_monotone(self):
        mid = {"first_pass_rate": 0.5, "norm_attempts": 0.5, "norm_cost": 0.5,
               "plan_stability": 0.5, "challenge_rate": 0.5}
        f = eh.compute_fitness(mid)
        self.assertGreaterEqual(f, 0.0)
        self.assertLessEqual(f, 1.0)

    def test_aggregate_first_pass_rate(self):
        results = [
            {"passed": True, "attempts": 1, "cost": 0.0, "challenged": False, "plan_changes": 0},
            {"passed": True, "attempts": 2, "cost": 0.0, "challenged": False, "plan_changes": 0},
            {"passed": False, "attempts": 3, "cost": 0.0, "challenged": True, "plan_changes": 1},
        ]
        m = eh.aggregate(results)
        self.assertAlmostEqual(m["first_pass_rate"], 1 / 3)   # only the 1-attempt pass counts
        self.assertAlmostEqual(m["challenge_rate"], 1 / 3)
        self.assertEqual(m["n"], 3)

    def test_aggregate_empty(self):
        m = eh.aggregate([])
        self.assertEqual(m["n"], 0)
        self.assertEqual(m["first_pass_rate"], 0.0)


class TestSuiteAndRun(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        # Release the pooled SQLite connection before unlinking the temp db, or Windows
        # raises PermissionError (WinError 32: file in use) on the open inode.
        from memory import experience
        experience._reset_schema_cache()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_load_suite_reads_real_golden_goals(self):
        # Resolve the shipped suite from THIS test file's repo root (not config.EVAL_SUITE_DIR,
        # which mis-resolves to a sub-dir when the repo runs from a worktree with no .env).
        suite = Path(__file__).resolve().parents[1] / "learning" / "eval_suite"
        goals = eh.load_suite(suite)   # the shipped learning/eval_suite
        self.assertGreaterEqual(len(goals), 1)
        self.assertTrue(all("verify" in g and g["verify"].get("held_out") for g in goals))

    def test_run_suite_with_injected_runner_records_row(self):
        db = self.dir / "x.db"
        (self.dir / "g1.json").write_text(json.dumps(
            {"id": "g1", "goal": "x", "verify": {"held_out": True}}), encoding="utf-8")

        def runner(goal):
            return {"passed": True, "attempts": 1}

        with mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True):
            out = eh.run_suite(runner=runner, suite_dir=self.dir, db_path=db)
        self.assertEqual(out["status"], "scored")
        self.assertEqual(out["fitness"], eh.compute_fitness(out))

    def test_run_suite_no_runner_records_marker(self):
        db = self.dir / "y.db"
        out = eh.run_suite(runner=None, suite_dir=self.dir, db_path=db)
        self.assertEqual(out["status"], "no_runner")

    def test_fitness_panel_renders_series(self):
        db = self.dir / "p.db"
        from memory import experience
        experience.record_eval({"fitness": 0.4}, db_path=db)
        experience.record_eval({"fitness": 0.6}, db_path=db)
        panel = eh.fitness_panel(db_path=db)
        self.assertIn("now=0.600", panel)
        self.assertIn("▲", panel)              # improved over the window

    def test_fitness_panel_empty(self):
        db = self.dir / "empty.db"
        self.assertIn("no eval points", eh.fitness_panel(db_path=db))


if __name__ == "__main__":
    unittest.main()
