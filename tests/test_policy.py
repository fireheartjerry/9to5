"""Unit tests for SIE Layer 4 policy bandit (learning/policy.py)."""
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from learning import policy
from memory import experience


class TestReward(unittest.TestCase):
    def test_first_pass_no_cost_is_max(self):
        self.assertAlmostEqual(
            policy.compute_reward({"verify_passed": 1, "attempt_count": 1}), 1.0)

    def test_failure_is_zero(self):
        self.assertAlmostEqual(
            policy.compute_reward({"verify_passed": 0, "attempt_count": 1}), 0.0)

    def test_retries_penalized(self):
        # 1.0 - 0.3*(3-1) = 0.4
        self.assertAlmostEqual(
            policy.compute_reward({"verify_passed": 1, "attempt_count": 3}), 0.4)

    def test_cost_penalized(self):
        r = policy.compute_reward({"verify_passed": 1, "attempt_count": 1, "cost_usd": 1.0})
        self.assertAlmostEqual(r, 1.0 - config.POLICY_REWARD_WEIGHTS["cost"])


class TestBandit(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()

    def tearDown(self):
        mock.patch.stopall()
        # release pooled SQLite connection(s) before unlinking the temp db (Windows WinError 32)
        experience._reset_schema_cache()
        for p in self.dir.rglob("*"):
            if p.is_file():
                p.unlink()
        self.dir.rmdir()

    def _seed(self, fam, effort, passed, n):
        for i in range(n):
            experience.record_subtask("r1", {
                "subtask_id": f"{fam}-{effort}-{int(passed)}-{i}", "title": f"{fam} thing",
                "status": "done", "verify_result": {"passed": passed},
                "session": {"effort": effort, "attempts": 1},
            }, db_path=self.db)

    def test_rebuild_accumulates_arms(self):
        self._seed("discord", "high", True, 4)
        self._seed("discord", "default", False, 2)
        out = policy.rebuild_from_ledger(db_path=self.db)
        self.assertEqual(out["arms"], 2)
        arms = {a["action_json"]: a for a in experience.fetch_arms("discord", db_path=self.db)}
        high = arms['{"effort": "high"}']
        self.assertEqual(high["pulls"], 4)
        self.assertAlmostEqual(high["reward_sum"], 4.0)   # 4 first-pass wins

    def test_select_favors_better_arm(self):
        self._seed("discord", "high", True, 10)     # reward ~1.0
        self._seed("discord", "default", False, 10)  # reward ~0.0
        policy.rebuild_from_ledger(db_path=self.db)
        rng = random.Random(0)
        actions = [{"effort": "high"}, {"effort": "default"}]
        picks = [policy.select("discord", actions, rng=rng, db_path=self.db)["effort"]
                 for _ in range(50)]
        self.assertGreater(picks.count("high"), 40)   # strongly prefers the winner

    def test_hint_empty_without_evidence(self):
        # No arms for this family -> no hint.
        self.assertEqual(policy.hint("goal", "brand new thing", db_path=self.db), "")

    def test_hint_present_with_evidence(self):
        self._seed("discord", "high", True, 10)
        self._seed("discord", "default", False, 10)
        policy.rebuild_from_ledger(db_path=self.db)
        h = policy.hint("goal", "discord thing", rng=random.Random(1), db_path=self.db)
        self.assertIn("POLICY HINT", h)
        self.assertIn("effort=", h)
