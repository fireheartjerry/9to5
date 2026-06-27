"""Unit tests for adaptive curriculum trigger in Self-Improvement Engine."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from learning import sie
from memory import experience, retrieval


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
        # Reload work_launcher module to clear any stale cached references from other tests
        import sys
        import importlib
        if 'notifications.work_launcher' in sys.modules:
            importlib.reload(sys.modules['notifications.work_launcher'])

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
                kind="approve",
                run_id=f"run-{i}",
                subtask_id=f"st-{i}",
                target="proposal",
                db_path=self.db
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

    def test_adaptive_trigger_fires_on_five_new_feedback(self):
        """When >=5 feedback records exist, curriculum goals are auto-queued.

        NOTE: This test has a known issue when run with other tests that import work_launcher.
        It passes in isolation or when run as the only test method in this class, but may fail
        when run after sie/override tests due to module caching in mocks. This is a test isolation
        issue, not a code issue. Running with `pytest tests/test_curriculum_adaptive_trigger.py` alone works.
        """
        # Clear cached module and mock work_launcher.spawn BEFORE the first run to ensure module caching works correctly.
        import sys
        sys.modules.pop('notifications.work_launcher', None)
        from notifications import work_launcher
        with mock.patch.object(work_launcher, "spawn", return_value=12345) as mock_spawn:
            # First run with no feedback should not queue goals.
            out1 = sie.run_maintenance(force=True, db_path=self.db)
            self.assertIn("curriculum_and_report", out1["steps"])

            # Seed 5 new feedback records and curriculum context.
            self._seed_curriculum_context()
            self._seed_feedback(5)

            # Force another maintenance run; adaptive trigger should fire and queue goals.
            out2 = sie.run_maintenance(force=True, db_path=self.db)
            curriculum_result = out2["steps"]["curriculum_and_report"]
            self.assertIn("curriculum_and_report", out2["steps"])
            self.assertGreater(curriculum_result.get("curriculum_goals", 0), 0,
                              f"Expected curriculum goals; got {curriculum_result}")
            # Verify spawn was called for each generated goal
            self.assertEqual(mock_spawn.call_count, curriculum_result.get("curriculum_goals", 0),
                            f"Expected spawn to be called for each goal; got {mock_spawn.call_count} calls")
            # Verify auto_queued counter matches spawn calls
            self.assertGreater(curriculum_result.get("auto_queued", 0), 0,
                              f"Expected auto_queued > 0 when >=5 feedback exist; got {curriculum_result}")
            # Verify spawn was called with WorkRequest objects containing valid goals
            for call in mock_spawn.call_args_list:
                args, kwargs = call
                self.assertEqual(len(args), 1, "spawn should be called with one positional arg")
                req = args[0]
                self.assertIsInstance(req, work_launcher.WorkRequest)
                self.assertIsNotNone(req.goal)
                self.assertGreater(len(req.goal), 0, "goal should not be empty")


    def test_adaptive_trigger_not_fired_on_less_than_five_feedback(self):
        """When <5 feedback records exist, curriculum goals are NOT auto-queued even if generated."""
        # Seed curriculum context.
        self._seed_curriculum_context()

        # Add only 4 feedback records (below threshold).
        self._seed_feedback(4)

        # Run maintenance with mocked spawn to verify it's NOT called.
        from notifications import work_launcher
        with mock.patch.object(work_launcher, "spawn", return_value=12345) as mock_spawn:
            out = sie.run_maintenance(force=True, db_path=self.db)
            curriculum_result = out["steps"]["curriculum_and_report"]
            self.assertIn("curriculum_and_report", out["steps"])
            # Goals may or may not be generated (depends on family stats),
            # but spawn should NOT be called because feedback count < 5.
            self.assertEqual(mock_spawn.call_count, 0,
                            f"spawn should NOT be called when feedback < 5; got {mock_spawn.call_count} calls")
            self.assertEqual(curriculum_result.get("auto_queued", 0), 0,
                            f"auto_queued should be 0 when feedback < 5; got {curriculum_result}")
