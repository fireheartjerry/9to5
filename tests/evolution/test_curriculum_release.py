"""Unit tests for SIE curriculum (subsystem C) + releases/attribution (subsystem H)."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from learning import curriculum, release
from memory import experience


class _Base(unittest.TestCase):
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
        for p in sorted(self.dir.rglob("*"), reverse=True):
            if p.is_dir():
                p.rmdir()
        self.dir.rmdir()

    def _fam(self, fam, passed, n):
        for i in range(n):
            experience.record_subtask("r1", {
                "subtask_id": f"{fam}-{int(passed)}-{i}", "title": f"{fam} task",
                "status": "done", "verify_result": {"passed": passed},
                "session": {"attempts": 1, "effort": "high"},
            }, db_path=self.db)


class TestCurriculum(_Base):
    def test_weakest_family_first(self):
        self._fam("alpha", True, 5)              # strong: 100%
        self._fam("beta", False, 5)             # weak: 0%
        stats = curriculum.family_stats(min_support=3, db_path=self.db)
        self.assertEqual(stats[0]["family"], "beta")
        self.assertAlmostEqual(stats[0]["first_pass_rate"], 0.0)

    def test_generate_goals_targets_weak(self):
        self._fam("alpha", True, 5)
        self._fam("beta", False, 5)
        goals = curriculum.generate_goals(n=1, min_support=3, db_path=self.db)
        self.assertEqual(len(goals), 1)
        self.assertEqual(goals[0]["family"], "beta")
        self.assertTrue(goals[0]["self_generated"])
        self.assertIn("beta", goals[0]["goal"])

    def test_min_support_filters_noise(self):
        self._fam("tiny", False, 1)
        self.assertEqual(curriculum.family_stats(min_support=3, db_path=self.db), [])

    def test_write_suggestions(self):
        self._fam("beta", False, 5)
        goals = curriculum.generate_goals(n=1, min_support=3, db_path=self.db)
        out = self.dir / "curriculum.md"
        curriculum.write_suggestions(goals, out)
        self.assertIn("beta", out.read_text(encoding="utf-8"))


class TestRelease(_Base):
    def test_adapter_model_card(self):
        card = release.model_card("adapter", {
            "tag": "9to5-brain:v1", "base_model": "qwen2.5-coder:7b", "role": "planner",
            "n_train_examples": 80, "trained_at": "now", "state": "champion", "lora_path": "/x"})
        self.assertIn("9to5-brain:v1", card)
        self.assertIn("frozen", card)
        self.assertIn("planner", card)

    def test_attribution_counts_and_fitness_delta(self):
        experience.record_eval({"fitness": 0.4}, db_path=self.db)
        experience.record_eval({"fitness": 0.7}, db_path=self.db)
        experience.upsert_lesson("effort", "beta", "prefer high", support_count=5,
                                 win_rate=0.9, db_path=self.db)
        attr = release.attribution(db_path=self.db)
        self.assertEqual(attr["lessons"], 1)
        self.assertAlmostEqual(attr["fitness"]["delta"], 0.3)
        self.assertEqual(attr["fitness"]["points"], 2)

    def test_render_and_write_report(self):
        experience.record_eval({"fitness": 0.5}, db_path=self.db)
        experience.record_eval({"fitness": 0.8}, db_path=self.db)
        out = self.dir / "report.md"
        release.write_report(out, db_path=self.db)
        text = out.read_text(encoding="utf-8")
        self.assertIn("Self-Improvement Report", text)
        self.assertIn("Fitness", text)
