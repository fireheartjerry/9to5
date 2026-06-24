"""Unit tests for SIE counterfactual replay + shadow/canary rollout."""
import random
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from learning import counterfactual, rollout
from memory import experience


class TestCounterfactual(unittest.TestCase):
    def test_positive_uplift_when_challenger_passes_more(self):
        rows = [{"verify_passed": 0}, {"verify_passed": 0}, {"verify_passed": 1}]
        out = counterfactual.estimate_uplift(rows, lambda r: True)   # challenger passes all
        self.assertAlmostEqual(out["champion_rate"], 1 / 3)
        self.assertEqual(out["challenger_rate"], 1.0)
        self.assertAlmostEqual(out["uplift"], 2 / 3)

    def test_replay_error_counts_as_fail(self):
        rows = [{"verify_passed": 1}]
        def boom(r):
            raise RuntimeError("nope")
        out = counterfactual.estimate_uplift(rows, boom)
        self.assertEqual(out["challenger_rate"], 0.0)

    def test_empty(self):
        out = counterfactual.estimate_uplift([], lambda r: True)
        self.assertEqual(out["n"], 0)


class TestRollout(unittest.TestCase):
    def test_advances_through_stages_with_samples(self):
        s = rollout.next_stage("shadow", fitness=0.8, baseline=0.7, n=50, min_samples=20)
        self.assertEqual(s, "canary")
        s = rollout.next_stage("canary", fitness=0.8, baseline=0.7, n=50, min_samples=20)
        self.assertEqual(s, "champion")
        s = rollout.next_stage("champion", fitness=0.8, baseline=0.7, n=50, min_samples=20)
        self.assertEqual(s, "champion")   # terminal

    def test_holds_without_enough_samples(self):
        self.assertEqual(
            rollout.next_stage("canary", fitness=0.9, baseline=0.7, n=3, min_samples=20),
            "canary")

    def test_regression_rolls_back(self):
        self.assertEqual(
            rollout.next_stage("canary", fitness=0.5, baseline=0.7, n=50, min_samples=20),
            rollout.ROLLED_BACK)

    def test_should_use_candidate(self):
        self.assertFalse(rollout.should_use_candidate("shadow"))
        self.assertTrue(rollout.should_use_candidate("champion"))
        self.assertTrue(rollout.should_use_candidate(
            "canary", rng=random.Random(0), canary_fraction=1.0))
        self.assertFalse(rollout.should_use_candidate(
            "canary", rng=random.Random(0), canary_fraction=0.0))


class TestPerRoleAdapters(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "SIE_KILL_SWITCH", False).start()
        mock.patch.object(config, "OLLAMA_MODEL", "qwen2.5-coder:7b").start()

    def tearDown(self):
        mock.patch.stopall()
        # release pooled SQLite connection(s) before unlinking the temp db (Windows WinError 32)
        experience._reset_schema_cache()
        for p in self.dir.rglob("*"):
            if p.is_file():
                p.unlink()
        self.dir.rmdir()

    def test_each_role_serves_its_own_tag(self):
        from learning import finetune
        pid = experience.register_adapter(base_model="b", tag="9to5-brain:planner-v1",
                                          role="planner", lora_path="/p", db_path=self.db)
        rid = experience.register_adapter(base_model="b", tag="9to5-brain:replanner-v1",
                                          role="replanner", lora_path="/r", db_path=self.db)
        experience.promote_adapter(pid, db_path=self.db)
        experience.promote_adapter(rid, db_path=self.db)
        self.assertEqual(finetune.active_brain_tag("planner", db_path=self.db),
                         "9to5-brain:planner-v1")
        self.assertEqual(finetune.active_brain_tag("replanner", db_path=self.db),
                         "9to5-brain:replanner-v1")
        # A role with no adapter falls back to the base model.
        self.assertEqual(finetune.active_brain_tag("elaborator", db_path=self.db),
                         "qwen2.5-coder:7b")

    def test_promoting_a_role_does_not_disturb_another(self):
        a = experience.register_adapter(base_model="b", tag="t-a", role="planner",
                                        lora_path="/a", db_path=self.db)
        experience.promote_adapter(a, db_path=self.db)
        b = experience.register_adapter(base_model="b", tag="t-b", role="replanner",
                                        lora_path="/b", db_path=self.db)
        experience.promote_adapter(b, db_path=self.db)
        champs = {c["role"]: c["tag"]
                  for c in experience.fetch_adapters("champion", db_path=self.db)}
        self.assertEqual(champs, {"planner": "t-a", "replanner": "t-b"})


if __name__ == "__main__":
    unittest.main()
