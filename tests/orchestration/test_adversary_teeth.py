"""Unit tests for the adversary 'teeth': the pre-PR review + PR-hold gate decision."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from orchestrator import Orchestrator
from state.task import TaskState


class TestPrGate(unittest.TestCase):
    def setUp(self):
        # _prGate is now an instance method that consults run state (for the night-mode degraded
        # check). A fresh, healthy (non-degraded) state exercises the normal day-mode hold paths.
        self.orch = Orchestrator()
        self.state = TaskState.create("g", 1.0)

    def test_approved_creates_pr(self):
        self.assertEqual(self.orch._prGate({"verdict": "approved"}, True, self.state), (True, ""))

    def test_no_pr_flag_skips(self):
        self.assertEqual(self.orch._prGate({"verdict": "approved"}, False, self.state), (False, "--no-pr"))

    def test_challenged_holds_pr_with_concerns(self):
        # HOLD flag on + blocking challenge -> the PR is actually held;
        # night mode is the only sanctioned ship-anyway escape (tested in test_horizon_fill).
        create, reason = self.orch._prGate(
            {"verdict": "challenged", "concerns": ["secret leak", "no rollback"]}, True, self.state)
        self.assertFalse(create)   # a blocking challenge HOLDS the PR (day mode, non-degraded)
        self.assertIn("HOLD", reason)
        self.assertIn("secret leak", reason)

    def test_challenged_respects_disable_flag(self):
        with mock.patch.object(config, "ADVERSARY_PR_HOLD_ENABLED", False):
            create, _ = self.orch._prGate({"verdict": "challenged", "concerns": ["x"]}, True, self.state)
        self.assertTrue(create)   # hold disabled -> PR proceeds


class TestPrePrAdversary(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._patch = mock.patch.object(config, "STATE_DIR", self.dir)
        self._patch.start()
        self.state = TaskState.create("goal", 1.0)
        self.state.meta["goal_elaborated"] = "goal"
        self.state.addSubtask("a", "da")
        self.obs = mock.Mock()
        self.obs.writeNote.return_value = {"ok": True, "rel_path": "n.md"}

    def tearDown(self):
        self._patch.stop()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def _orch(self, review):
        return Orchestrator(brain=mock.Mock(), obs=self.obs,
                            run_claude=lambda *a, **k: {"ok": True, "stdout": "", "is_error": False},
                            replan=lambda *a, **k: {"action": "keep"}, review=review)

    def test_returns_verdict_and_records_review(self):
        review = mock.Mock(return_value={"verdict": "challenged", "concerns": ["leak"],
                                         "notes": "", "stub": False})
        rv = self._orch(review)._prePrAdversary(self.state)
        self.assertEqual(rv["verdict"], "challenged")
        self.assertTrue(any(r["subtask_id"] == "pre_pr" for r in self.state.data["adversary_reviews"]))

    def test_review_error_approves_conservatively(self):
        def boom(*a, **k):
            raise RuntimeError("brain down")
        rv = self._orch(boom)._prePrAdversary(self.state)
        self.assertEqual(rv["verdict"], "approved")   # never blocks a run on a reviewer error
