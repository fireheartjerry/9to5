"""Unit tests for SIE Layer 5 distillation + LoRA cycle (distill.py / finetune.py)."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from learning import distill, finetune
from memory import experience


class TestDistillBuilder(unittest.TestCase):
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

    def _gold(self, st_id, spec="{\"effort\":\"high\"}"):
        experience.record_subtask("r1", {
            "subtask_id": st_id, "title": f"do {st_id}", "status": "done",
            "verify_result": {"passed": True}, "verify": {"cmd": "pytest", "expect": "exit_zero"},
            "session": {"attempts": 1, "effort": "high", "invocation_spec": json.loads(spec)},
            "_adversary_verdict": "approved", "_adversary_stub": 0,
        }, db_path=self.db)

    def test_build_emits_clean_pairs(self):
        self._gold("st-001")
        self._gold("st-002")
        out_path = self.dir / "ds.jsonl"
        res = distill.build(db_path=self.db, out_path=out_path, suite=[])
        self.assertEqual(res["examples"], 2)
        lines = out_path.read_text(encoding="utf-8").strip().splitlines()
        self.assertEqual(len(lines), 2)
        rec = json.loads(lines[0])
        self.assertIn("Author the JSON invocation spec", rec["prompt"])
        self.assertTrue(rec["completion"])

    def test_build_skips_rows_without_spec(self):
        experience.record_subtask("r1", {
            "subtask_id": "st-x", "title": "no spec", "status": "done",
            "verify_result": {"passed": True}, "session": {"attempts": 1, "effort": "high"},
        }, db_path=self.db)
        res = distill.build(db_path=self.db, suite=[])
        self.assertEqual(res["examples"], 0)


class TestModelfileAndCycle(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()
        mock.patch.object(config, "SIE_KILL_SWITCH", False).start()
        mock.patch.object(config, "OLLAMA_MODEL", "qwen2.5-coder:7b").start()
        mock.patch.object(config, "BRAIN_MODEL_TAG", "9to5-brain").start()
        # routing/promotion tests here aren't about Ollama servability (covered in
        # test_finetune_routing); treat every promoted tag as servable so active_brain_tag routes to
        # it instead of falling back to base on the liveness check.
        mock.patch.object(finetune, "_servable", lambda tag: True).start()

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

    def _gold(self, n):
        for i in range(n):
            experience.record_subtask("r1", {
                "subtask_id": f"st-{i}", "title": f"do {i}", "status": "done",
                "verify_result": {"passed": True}, "verify": {"cmd": "c", "expect": "exit_zero"},
                "session": {"attempts": 1, "invocation_spec": {"effort": "high", "i": i}},
                "_adversary_verdict": "approved", "_adversary_stub": 0,
            }, db_path=self.db)

    def test_modelfile_format(self):
        self.assertEqual(finetune.modelfile_text("base:7b", "/x/lora"),
                         "FROM base:7b\nADAPTER /x/lora\n")

    def test_cycle_skips_when_not_enough(self):
        self._gold(2)
        out = finetune.run_finetune_cycle(out_dir=self.dir, min_examples=10, db_path=self.db)
        self.assertEqual(out["skipped"], "not_enough")

    def test_cycle_skips_without_trainer(self):
        self._gold(5)
        with mock.patch.object(finetune, "default_trainer", return_value=None):
            out = finetune.run_finetune_cycle(out_dir=self.dir, min_examples=3,
                                              trainer=None, db_path=self.db)
        self.assertEqual(out["skipped"], "no_trainer")

    def test_cycle_trains_registers_and_builds_model(self):
        self._gold(5)
        created = {}

        def fake_trainer(ds_path, out_dir):
            (Path(out_dir) / "lora").mkdir(exist_ok=True)
            return str(Path(out_dir) / "lora")

        def fake_ollama(tag, mf):
            created["tag"], created["mf"] = tag, mf

        out = finetune.run_finetune_cycle(
            out_dir=self.dir, min_examples=3, trainer=fake_trainer,
            ollama_runner=fake_ollama, db_path=self.db)
        self.assertEqual(out["status"], "trained")
        self.assertEqual(out["tag"], "9to5-brain:v1")
        self.assertEqual(created["tag"], "9to5-brain:v1")
        self.assertTrue(Path(created["mf"]).exists())
        # Registered as a challenger (NOT auto-promoted).
        self.assertEqual(experience.fetch_adapters("challenger", db_path=self.db)[0]["tag"],
                         "9to5-brain:v1")

    def test_kill_switch_skips_cycle(self):
        with mock.patch.object(config, "SIE_KILL_SWITCH", True):
            out = finetune.run_finetune_cycle(out_dir=self.dir, db_path=self.db)
        self.assertEqual(out["skipped"], "kill_switch")

    def test_active_tag_routing_and_rollback(self):
        # No adapter -> base. Promote -> tag. Kill switch -> base. Rollback -> base.
        self.assertEqual(finetune.active_brain_tag(db_path=self.db), "qwen2.5-coder:7b")
        aid = experience.register_adapter(base_model="qwen2.5-coder:7b", tag="9to5-brain:v1",
                                          lora_path="/x", state="challenger", db_path=self.db)
        experience.promote_adapter(aid, db_path=self.db)
        self.assertEqual(finetune.active_brain_tag(db_path=self.db), "9to5-brain:v1")
        with mock.patch.object(config, "SIE_KILL_SWITCH", True):
            self.assertEqual(finetune.active_brain_tag(db_path=self.db), "qwen2.5-coder:7b")
        finetune.rollback_to_base(db_path=self.db)
        self.assertEqual(finetune.active_brain_tag(db_path=self.db), "qwen2.5-coder:7b")

    def test_consider_promotion_gate(self):
        aid = experience.register_adapter(base_model="b", tag="9to5-brain:v1", lora_path="/x",
                                          state="challenger", db_path=self.db)
        rej = finetune.consider_promotion(aid, challenger_fitness=0.4, champion_fitness=0.5,
                                          db_path=self.db)
        self.assertEqual(rej["decision"], "reject")
        prom = finetune.consider_promotion(aid, challenger_fitness=0.7, champion_fitness=0.5,
                                           db_path=self.db)
        self.assertEqual(prom["decision"], "promote")
        self.assertEqual(finetune.active_brain_tag(db_path=self.db), "9to5-brain:v1")
