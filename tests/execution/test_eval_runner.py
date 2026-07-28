"""Tests for the live eval runner registry + automatic adapter promotion."""
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from learning import adapter_promotion, eval_harness, eval_runner
from memory import experience


class TestEvalRunner(unittest.TestCase):
    def setUp(self):
        eval_runner.clear()   # an Orchestrator built by another test may have registered one
        self.verify_temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.verify_temp.cleanup)

    def _authority(self):
        from agents.review.verification import issueDiagnosticVerificationCommandAuthority

        def contained(request):
            return subprocess.run(
                list(request.argv),
                cwd=request.work_dir,
                capture_output=True,
                text=True,
                timeout=request.timeout_seconds,
                check=False,
            )

        return issueDiagnosticVerificationCommandAuthority(
            transaction_id="tx_eval_runner_test",
            proposed_revision="1" * 40,
            resource_id="eval_verifier_test",
            work_dir=self.verify_temp.name,
            image_digest="2" * 64,
            security_profile_digest="3" * 64,
            command_policy_digest="4" * 64,
            watchdog_generation=1,
            deadline="2099-01-01T00:00:00+00:00",
            runner=contained,
        )

    def _verify(self, goal):
        return eval_runner.verify_runner(
            goal,
            verification_authority=self._authority(),
            work_dir=self.verify_temp.name,
        )

    def tearDown(self):
        eval_runner.clear()
        mock.patch.stopall()

    def test_active_runner_defaults_to_verify_runner(self):
        eval_runner.clear()
        self.assertIs(eval_runner.active_runner(), eval_runner.verify_runner)

    def test_registered_runner_takes_over(self):
        def my_runner(goal):
            return {"passed": True, "attempts": 1}
        eval_runner.register(goal_runner=my_runner)
        self.assertIs(eval_runner.active_runner(), my_runner)

    def test_verify_runner_runs_real_check(self):
        # A trivially-true verify passes; a failing one fails.
        ok = self._verify({"verify": {"cmd": "python -c \"assert True\"",
                                      "expect": "exit_zero"}})
        bad = self._verify({"verify": {"cmd": "python -c \"assert False\"",
                                       "expect": "exit_zero"}})
        self.assertTrue(ok["passed"])
        self.assertFalse(bad["passed"])

    def test_verify_runner_without_exact_authority_fails_closed(self):
        result = eval_runner.verify_runner(
            {"verify": {"cmd": "python -c \"assert True\"", "expect": "exit_zero"}}
        )
        self.assertFalse(result["passed"])
        self.assertEqual(result["reason"], "verification_authority_unavailable")

    def test_run_suite_with_verify_runner_makes_real_fitness(self):
        d = Path(tempfile.mkdtemp())
        try:
            import json
            (d / "g.json").write_text(json.dumps(
                {"id": "g", "verify": {"cmd": "python -c \"assert True\"", "expect": "exit_zero"}}),
                encoding="utf-8")
            db = d / "x.db"
            out = eval_harness.run_suite(runner=self._verify, suite_dir=d, db_path=db)
            self.assertEqual(out["status"], "scored")
            self.assertGreater(out["fitness"], 0.0)   # real, not a no_runner marker
        finally:
            # release pooled SQLite connection(s) before unlinking the temp db (Windows WinError 32)
            experience._reset_schema_cache()
            for p in d.glob("*"):
                p.unlink()
            d.rmdir()


class TestAdapterPromotion(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        eval_runner.clear()   # isolate from any orchestrator-registered evaluator
        mock.patch.object(config, "SIE_KILL_SWITCH", False).start()
        mock.patch.object(config, "OLLAMA_MODEL", "qwen2.5-coder:7b").start()

    def tearDown(self):
        eval_runner.clear()
        mock.patch.stopall()
        # release pooled SQLite connection(s) before unlinking the temp db (Windows WinError 32)
        experience._reset_schema_cache()
        for p in self.dir.rglob("*"):
            if p.is_file():
                p.unlink()
        self.dir.rmdir()

    def test_skips_without_evaluator(self):
        experience.register_adapter(base_model="b", tag="t", lora_path="/x", db_path=self.db)
        self.assertEqual(adapter_promotion.run(db_path=self.db)["skipped"], "no_evaluator")

    def test_promotes_better_challenger(self):
        experience.register_adapter(base_model="b", tag="9to5-brain:v1", lora_path="/x",
                                          db_path=self.db)
        # Champion = base (no champion adapter) at fitness 0.5; challenger at 0.8.
        fit = {"qwen2.5-coder:7b": 0.5, "9to5-brain:v1": 0.8}
        eval_runner.register(fitness_under_tag=lambda tag: fit[tag])
        out = adapter_promotion.run(db_path=self.db)
        self.assertEqual(out["9to5-brain:v1"]["decision"], "promote")
        self.assertEqual(experience.get_champion_adapter(db_path=self.db)["tag"], "9to5-brain:v1")

    def test_rejects_regressing_challenger(self):
        experience.register_adapter(base_model="b", tag="9to5-brain:v1", lora_path="/x",
                                    db_path=self.db)
        fit = {"qwen2.5-coder:7b": 0.8, "9to5-brain:v1": 0.5}
        eval_runner.register(fitness_under_tag=lambda tag: fit[tag])
        out = adapter_promotion.run(db_path=self.db)
        self.assertEqual(out["9to5-brain:v1"]["decision"], "reject")
        self.assertIsNone(experience.get_champion_adapter(db_path=self.db))
