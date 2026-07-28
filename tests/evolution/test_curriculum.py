"""Unit tests for SIE curriculum (subsystem C) + releases/attribution (subsystem H).

Consolidated from test_curriculum_release.py and test_curriculum_adaptive_trigger.py:
both center on learning/curriculum.py -- the first as direct unit tests of
family_stats/generate_goals/write_suggestions (+ learning/release.py), the second
as an integration test of the adaptive trigger that auto-queues curriculum goals
from learning/sie.py::_curriculum_and_report once >=5 new feedback records land.
"""

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import config
from learning import curriculum, release, sie
from memory import experience, retrieval

# The code under test (learning/sie.py::_curriculum_and_report) resolves spawn at call
# time as `from notifications import work_launcher; work_launcher.spawn(...)` -- a plain
# attribute lookup on this same module object. Import it once here and patch that
# attribute with mock.patch.object; no sys.modules pop/reload needed (reloading forked
# the module identity, breaking WorkRequest isinstance checks and leaking fresh spawn
# bindings depending on test order).
from notifications import work_launcher


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
            experience.record_subtask(
                "r1",
                {
                    "subtask_id": f"{fam}-{int(passed)}-{i}",
                    "title": f"{fam} task",
                    "status": "done",
                    "verify_result": {"passed": passed},
                    "session": {"attempts": 1, "effort": "high"},
                },
                db_path=self.db,
            )


class TestCurriculum(_Base):
    def test_weakest_family_first(self):
        self._fam("alpha", True, 5)  # strong: 100%
        self._fam("beta", False, 5)  # weak: 0%
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
        card = release.model_card(
            "adapter",
            {
                "tag": "9to5-brain:v1",
                "base_model": "qwen2.5-coder:7b",
                "role": "planner",
                "n_train_examples": 80,
                "trained_at": "now",
                "state": "champion",
                "lora_path": "/x",
            },
        )
        self.assertIn("9to5-brain:v1", card)
        self.assertIn("frozen", card)
        self.assertIn("planner", card)

    def test_attribution_counts_and_fitness_delta(self):
        experience.record_eval({"fitness": 0.4}, db_path=self.db)
        experience.record_eval({"fitness": 0.7}, db_path=self.db)
        experience.upsert_lesson(
            "effort", "beta", "prefer high", support_count=5, win_rate=0.9, db_path=self.db
        )
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


class TestAdaptiveCurriculumTrigger(unittest.TestCase):
    """Verify that curriculum goals are auto-queued when >=5 new feedback records appear."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.db = self.dir / "experience.db"
        mock.patch.object(config, "CONTROL_DIR", self.dir / "control").start()
        mock.patch.object(config, "VAULT_DISK_ROOT", self.dir / "vault").start()
        mock.patch.object(config, "EXPERIENCE_LEDGER_ENABLED", True).start()
        mock.patch.object(config, "SIE_KILL_SWITCH", False).start()
        mock.patch.object(retrieval, "_embed_call", return_value=None).start()
        mock.patch.object(config, "EVAL_SUITE_DIR", self.dir / "nosuite").start()
        mock.patch.object(config, "SELFPLAY_ENABLED", False).start()
        mock.patch.object(config, "SIE_BOOTSTRAP", False).start()
        retrieval.reset_embed_cache()
        from platform_core.runtime.controller_state import issueDiagnosticControllerStateAuthority
        from platform_core.runtime.effect_guard import issueDiagnosticMaintenanceAuthority

        capability = object()
        self.controller_state_authority = issueDiagnosticControllerStateAuthority(
            root=self.dir / "controller",
            repository_id="repo_curriculum_test",
            controller_generation=1,
            process_capability=capability,
            expires_at="2099-01-01T00:00:00+00:00",
        )
        self.maintenance_authority = issueDiagnosticMaintenanceAuthority(
            operations={"sie_maintenance"},
            controller_generation=1,
            process_capability=capability,
            expires_at="2099-01-01T00:00:00+00:00",
        )

    def tearDown(self):
        mock.patch.stopall()
        experience._reset_schema_cache()
        for p in sorted(self.dir.rglob("*"), reverse=True):
            if p.is_file():
                p.unlink()
            elif p.is_dir():
                p.rmdir()
        self.dir.rmdir()

    def _seed_feedback(self, count: int):
        """Add count feedback records to the ledger."""
        for i in range(count):
            experience.record_feedback(
                kind="approve", run_id=f"run-{i}", subtask_id=f"st-{i}", target="proposal", db_path=self.db
            )

    def _seed_curriculum_context(self):
        """Seed enough subtasks so curriculum.generate_goals() produces results."""
        for i in range(10):
            experience.record_subtask(
                "r1",
                {
                    "subtask_id": f"st-{i}",
                    "title": "parsing code",
                    "status": "done",
                    "verify_result": {"passed": i > 3},  # first 4 fail, rest pass
                    "session": {"effort": "high", "attempts": 1},
                },
                db_path=self.db,
            )

    def _run_maintenance(self, **kwargs):
        return sie.run_maintenance(
            maintenance_authority=self.maintenance_authority,
            controller_state_authority=self.controller_state_authority,
            **kwargs,
        )

    def test_adaptive_trigger_fires_on_five_new_feedback(self):
        """When >=5 feedback records exist AND the opt-in auto-queue flag is enabled,
        curriculum goals are auto-queued. The auto-queue bypasses the human approval gate,
        so it is disabled by default (see CURRICULUM_AUTO_QUEUE_ENABLED) -- this test
        explicitly opts in to exercise the firing path."""
        with (
            mock.patch.object(config, "CURRICULUM_AUTO_QUEUE_ENABLED", True),
            mock.patch.object(work_launcher, "activeRun", return_value=None),
            mock.patch.object(work_launcher, "spawn", return_value=12345) as mock_spawn,
        ):
            # First run with no feedback should not queue goals.
            out1 = self._run_maintenance(force=True, db_path=self.db)
            self.assertIn("curriculum_and_report", out1["steps"])

            # Deterministically backdate the consolidation watermark. Both last_full_at
            # and feedback 'at' are second-precision isoformats, and the trigger counts
            # feedback with a STRICTLY greater timestamp -- so feedback seeded in the
            # same wall-clock second as the first run compares equal and never counts
            # (the old "module caching" flake was really this timing race, which warm
            # imports after other test files made near-certain to lose).
            st = sie._read_state()
            st["last_full_at"] = (datetime.now().astimezone() - timedelta(minutes=1)).isoformat(
                timespec="seconds"
            )
            sie._write_state(st)

            # Seed 5 new feedback records and curriculum context.
            self._seed_curriculum_context()
            self._seed_feedback(5)

            # Force another maintenance run; adaptive trigger should fire and queue goals.
            out2 = self._run_maintenance(force=True, db_path=self.db)
            curriculum_result = out2["steps"]["curriculum_and_report"]
            self.assertIn("curriculum_and_report", out2["steps"])
            self.assertGreater(
                curriculum_result.get("curriculum_goals", 0),
                0,
                f"Expected curriculum goals; got {curriculum_result}",
            )
            # Verify spawn was called for each generated goal
            self.assertEqual(
                mock_spawn.call_count,
                curriculum_result.get("curriculum_goals", 0),
                f"Expected spawn to be called for each goal; got {mock_spawn.call_count} calls",
            )
            # Verify auto_queued counter matches spawn calls
            self.assertGreater(
                curriculum_result.get("auto_queued", 0),
                0,
                f"Expected auto_queued > 0 when >=5 feedback exist; got {curriculum_result}",
            )
            # Verify spawn was called with WorkRequest objects containing valid goals
            for call in mock_spawn.call_args_list:
                args, kwargs = call
                self.assertEqual(len(args), 1, "spawn should be called with one positional arg")
                req = args[0]
                self.assertIsInstance(req, work_launcher.WorkRequest)
                self.assertIsNotNone(req.goal)
                self.assertGreater(len(req.goal), 0, "goal should not be empty")

    def test_adaptive_trigger_not_fired_by_default_even_with_five_feedback(self):
        """Security regression: CURRICULUM_AUTO_QUEUE_ENABLED defaults to False, so even the
        full run_maintenance -> curriculum_and_report path must NOT spawn any run when >=5
        feedback records exist, unless the flag is explicitly opted into."""
        # FULL_STACK flips CURRICULUM_AUTO_QUEUE_ENABLED on by default; pin it OFF here to assert the
        # ship-dark guardrail still holds (no spawn, "disabled") when the flag is not opted into.
        with mock.patch.object(work_launcher, "spawn", return_value=12345) as mock_spawn,                 mock.patch.object(config, "CURRICULUM_AUTO_QUEUE_ENABLED", False):
            self._seed_curriculum_context()
            self._seed_feedback(5)
            out = self._run_maintenance(force=True, db_path=self.db)
            curriculum_result = out["steps"]["curriculum_and_report"]
        mock_spawn.assert_not_called()
        self.assertEqual(curriculum_result.get("auto_queued", 0), 0)
        self.assertEqual(curriculum_result.get("auto_queue_skipped"), "disabled")

    def test_adaptive_trigger_not_fired_on_less_than_five_feedback(self):
        """When <5 feedback records exist, curriculum goals are NOT auto-queued even if generated."""
        # Seed curriculum context.
        self._seed_curriculum_context()

        # Add only 4 feedback records (below threshold).
        self._seed_feedback(4)

        # Run maintenance with mocked spawn to verify it's NOT called.
        with mock.patch.object(work_launcher, "spawn", return_value=12345) as mock_spawn:
            out = self._run_maintenance(force=True, db_path=self.db)
            curriculum_result = out["steps"]["curriculum_and_report"]
            self.assertIn("curriculum_and_report", out["steps"])
            # Goals may or may not be generated (depends on family stats),
            # but spawn should NOT be called because feedback count < 5.
            self.assertEqual(
                mock_spawn.call_count,
                0,
                f"spawn should NOT be called when feedback < 5; got {mock_spawn.call_count} calls",
            )
            self.assertEqual(
                curriculum_result.get("auto_queued", 0),
                0,
                f"auto_queued should be 0 when feedback < 5; got {curriculum_result}",
            )
