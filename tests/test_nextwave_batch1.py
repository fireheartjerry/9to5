"""Tests for NW1 human feedback, NW2 confidence, X2 safety."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from learning import confidence, human_feedback, safety
from memory import experience


class _Base(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()
        mock.patch.object(config, "OLLAMA_MODEL", "qwen2.5-coder:7b").start()
        mock.patch.object(config, "SIE_KILL_SWITCH", False).start()

    def tearDown(self):
        mock.patch.stopall()
        for p in self.dir.rglob("*"):
            if p.is_file():
                p.unlink()
        self.dir.rmdir()


class TestHumanFeedback(_Base):
    def test_record_and_stats(self):
        human_feedback.record("approve", run_id="r1", db_path=self.db)
        human_feedback.record("reject", run_id="r1", db_path=self.db)
        human_feedback.record("edit", target="plan", before={"a": 1}, after={"a": 2}, db_path=self.db)
        s = human_feedback.stats(db_path=self.db)
        self.assertEqual((s["positive"], s["negative"], s["corrections"]), (1, 1, 1))

    def test_correction_pairs_from_edits(self):
        human_feedback.record("edit", target="spec", before={"effort": "default"},
                              after={"effort": "high"}, db_path=self.db)
        pairs = human_feedback.correction_pairs(db_path=self.db)
        self.assertEqual(len(pairs), 1)
        self.assertIn("high", pairs[0]["chosen"])
        self.assertIn("default", pairs[0]["rejected"])


class TestConfidence(_Base):
    def _seed(self, passed, attempts, n):
        for i in range(n):
            experience.record_subtask("r1", {
                "subtask_id": f"{int(passed)}-{attempts}-{i}", "title": "t", "status": "done",
                "verify_result": {"passed": passed}, "session": {"attempts": attempts}},
                db_path=self.db)

    def test_calibrator_separates_and_recommends(self):
        self._seed(True, 1, 30)
        self._seed(False, 3, 30)
        cal = confidence.fit_from_ledger(db_path=self.db, epochs=400)
        p_easy = confidence.predict(cal, {"verify_passed": 1, "attempt_count": 1})
        self.assertEqual(confidence.recommend(0.1), "escalate")
        self.assertIn(confidence.recommend(p_easy), ("proceed", "fast"))

    def test_should_escalate_low_conf(self):
        cal = confidence.fit_from_ledger(db_path=self.db)  # empty -> ~0.5
        out = confidence.should_escalate(cal, {"verify_passed": 0}, threshold=0.9)
        self.assertTrue(out)


class TestSafety(_Base):
    def test_guard_blocks_brain_self_promotion(self):
        with self.assertRaises(safety.SelfPromotionError):
            safety.guard_promotion("brain")
        safety.guard_promotion("gate")   # allowed

    def test_invariants_healthy_then_violated(self):
        self.assertEqual(safety.verify_invariants(db_path=self.db), [])
        # Force an I1 violation: a champion adapter on a different base.
        aid = experience.register_adapter(base_model="someone-else:7b", tag="x",
                                          lora_path="/x", db_path=self.db)
        experience.promote_adapter(aid, db_path=self.db)
        v = safety.verify_invariants(db_path=self.db)
        self.assertTrue(any("I1" in s for s in v))

    def test_panic_to_stock_retires_champions(self):
        aid = experience.register_adapter(base_model="qwen2.5-coder:7b", tag="t",
                                          lora_path="/x", db_path=self.db)
        experience.promote_adapter(aid, db_path=self.db)
        out = safety.panic_to_stock(db_path=self.db)
        self.assertEqual(out["retired"], 1)
        self.assertEqual(experience.fetch_adapters("champion", db_path=self.db), [])


if __name__ == "__main__":
    unittest.main()
