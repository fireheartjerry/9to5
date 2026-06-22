"""Unit tests for the SIE Layer 3 promotion gate (learning/promotion.py)."""
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from learning import promotion, prompts
from memory import experience


class TestProportionZ(unittest.TestCase):
    def test_positive_when_a_better(self):
        self.assertGreater(promotion.proportion_z(90, 100, 50, 100), 1.64)

    def test_zero_when_equal(self):
        self.assertAlmostEqual(promotion.proportion_z(50, 100, 50, 100), 0.0)

    def test_negative_when_a_worse(self):
        self.assertLess(promotion.proportion_z(40, 100, 80, 100), 0.0)

    def test_undefined_returns_zero(self):
        self.assertEqual(promotion.proportion_z(1, 0, 1, 10), 0.0)


class TestDecide(unittest.TestCase):
    def setUp(self):
        mock.patch.object(config, "PROMPT_PROMOTE_MIN_USES", 20).start()
        mock.patch.object(config, "PROMPT_PROMOTE_Z", 1.64).start()

    def tearDown(self):
        mock.patch.stopall()

    def test_insufficient_below_min_uses(self):
        d = promotion.decide({"n": 50, "first_pass": 25}, {"n": 5, "first_pass": 5})
        self.assertEqual(d["decision"], "insufficient")

    def test_promote_on_significant_win(self):
        d = promotion.decide({"n": 100, "first_pass": 50}, {"n": 100, "first_pass": 90})
        self.assertEqual(d["decision"], "promote")

    def test_reject_on_weak_or_negative(self):
        d = promotion.decide({"n": 100, "first_pass": 80}, {"n": 100, "first_pass": 82})
        self.assertEqual(d["decision"], "reject")


class TestRunPromotions(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()
        mock.patch.object(config, "PROMPT_PROMOTE_MIN_USES", 5).start()
        mock.patch.object(config, "PROMPT_PROMOTE_Z", 1.64).start()

    def tearDown(self):
        mock.patch.stopall()
        for p in self.dir.rglob("*"):
            if p.is_file():
                p.unlink()
        self.dir.rmdir()

    def _tag_runs(self, prompt_id, n, passed):
        """Create n runs authored by prompt_id, each with one first-pass subtask outcome."""
        for i in range(n):
            rid = f"{prompt_id}-run-{i}"
            experience.record_run({"run_id": rid, "task_id": rid}, db_path=self.db)
            experience.tag_run_prompt(rid, str(prompt_id), db_path=self.db)
            experience.record_subtask(rid, {
                "subtask_id": "st-001", "status": "done",
                "verify_result": {"passed": passed}, "session": {"attempts": 1},
            }, db_path=self.db)

    def test_auto_promotes_clearly_better_challenger(self):
        champ_id = prompts.champion_id("orchestrator", "champ body", db_path=self.db)
        chall_id = prompts.propose("orchestrator", "challenger body", db_path=self.db)
        self._tag_runs(champ_id, 10, passed=False)   # champion: 0% first-pass
        self._tag_runs(chall_id, 10, passed=True)    # challenger: 100% first-pass
        out = promotion.run_promotions(rng=random.Random(0), db_path=self.db)
        self.assertEqual(out["orchestrator"]["decision"], "promote")
        self.assertEqual(prompts.get("orchestrator", "champ body", db_path=self.db),
                         "challenger body")

    def test_no_promotion_without_evidence(self):
        prompts.champion_id("orchestrator", "champ body", db_path=self.db)
        prompts.propose("orchestrator", "challenger body", db_path=self.db)
        out = promotion.run_promotions(rng=random.Random(0), db_path=self.db)
        self.assertEqual(out["orchestrator"]["decision"], "insufficient")
        self.assertEqual(prompts.get("orchestrator", "champ body", db_path=self.db), "champ body")


if __name__ == "__main__":
    unittest.main()
