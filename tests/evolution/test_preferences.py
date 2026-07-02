"""Unit tests for SIE DPO preference builder (learning/preferences.py) + DPO cycle."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from learning import finetune, preferences
from memory import experience


class TestPreferences(unittest.TestCase):
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

    def _sub(self, st_id, passed, spec):
        experience.record_subtask("r1", {
            "subtask_id": st_id, "title": "discord embed", "status": "done",
            "verify_result": {"passed": passed}, "verify": {"cmd": "c", "expect": "exit_zero"},
            "session": {"attempts": 1, "invocation_spec": spec},
        }, db_path=self.db)

    def test_pairs_built_from_pass_vs_fail_same_family(self):
        self._sub("st-1", True, {"effort": "high"})
        self._sub("st-2", False, {"effort": "default"})
        pairs = preferences.build_pairs(db_path=self.db, suite=[])
        self.assertEqual(len(pairs), 1)
        p = pairs[0]
        self.assertIn("high", p["chosen"])
        self.assertIn("default", p["rejected"])
        self.assertNotEqual(p["chosen"], p["rejected"])

    def test_no_pairs_without_a_failure(self):
        self._sub("st-1", True, {"effort": "high"})
        self._sub("st-2", True, {"effort": "xhigh"})
        self.assertEqual(preferences.build_pairs(db_path=self.db, suite=[]), [])

    def test_build_writes_jsonl(self):
        self._sub("st-1", True, {"effort": "high"})
        self._sub("st-2", False, {"effort": "default"})
        out = self.dir / "prefs.jsonl"
        res = preferences.build(db_path=self.db, out_path=out, suite=[])
        self.assertEqual(res["pairs"], 1)
        rec = json.loads(out.read_text(encoding="utf-8").strip())
        self.assertIn("chosen", rec)
        self.assertIn("rejected", rec)


class TestDpoCycle(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()
        mock.patch.object(config, "SIE_KILL_SWITCH", False).start()
        mock.patch.object(config, "OLLAMA_MODEL", "qwen2.5-coder:7b").start()
        mock.patch.object(config, "BRAIN_MODEL_TAG", "9to5-brain").start()

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

    def _pairs(self, n):
        for i in range(n):
            experience.record_subtask("r1", {
                "subtask_id": f"win-{i}", "title": f"fam{i} task", "status": "done",
                "verify_result": {"passed": True}, "session": {"attempts": 1,
                "invocation_spec": {"ok": i}}}, db_path=self.db)
            experience.record_subtask("r1", {
                "subtask_id": f"lose-{i}", "title": f"fam{i} task", "status": "failed",
                "verify_result": {"passed": False}, "session": {"attempts": 1,
                "invocation_spec": {"bad": i}}}, db_path=self.db)

    def test_dpo_skips_without_pairs(self):
        out = finetune.run_dpo_cycle(out_dir=self.dir, min_pairs=5, db_path=self.db)
        self.assertEqual(out["skipped"], "not_enough")

    def test_dpo_trains_with_seam(self):
        self._pairs(4)
        captured = {}

        def fake_trainer(pairs_path, out_dir, beta):
            captured["beta"] = beta
            (Path(out_dir) / "lora").mkdir(exist_ok=True)
            return str(Path(out_dir) / "lora")

        out = finetune.run_dpo_cycle(out_dir=self.dir, min_pairs=3, trainer=fake_trainer,
                                     db_path=self.db)
        self.assertEqual(out["status"], "trained")
        self.assertIn("dpo-v", out["tag"])
        self.assertEqual(captured["beta"], config.DPO_KL_BETA)
