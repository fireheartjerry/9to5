"""Tests for the self-improvement horizon-fill loop (RC-1/RC-2): a self-referential run whose
subtask queue drains with time left must author MORE work instead of finalizing early, while a
normal bounded run still finishes when its queue drains."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import config
from orchestrator import Orchestrator
from state.task import TaskState


def _iso(delta_hours: float) -> str:
    return (datetime.now().astimezone() + timedelta(hours=delta_hours)).isoformat(timespec="seconds")


class TestHorizonFill(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._patch = mock.patch.object(config, "STATE_DIR", self.dir)
        self._patch.start()
        self.state = TaskState.create("improve 9to5 indiscriminately", 8.0)
        self.state.setElaboratedGoal("improve 9to5 indiscriminately")
        self.state.meta["is_self_referential"] = True
        self.orch = Orchestrator()
        self.orch.obs = mock.Mock()
        self.dash = mock.Mock()

    def tearDown(self):
        self._patch.stop()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    # ---- _backfill -----------------------------------------------------
    def test_backfill_adds_subtasks_when_self_ref_with_time(self):
        batch = [{"title": "hunt bugs in X", "description": "d", "layer": 3, "verify": None},
                 {"title": "add tests for Y", "description": "d", "layer": 3, "verify": None}]
        with mock.patch.object(self.orch, "authorBackfillBatch", return_value=batch):
            added = self.orch._backfill(self.state, "arch", self.dash)
        self.assertEqual(added, 2)
        self.assertEqual(self.orch._pendingCount(self.state), 2)

    def test_backfill_respects_pending_cap(self):
        for i in range(config.MAX_SUBTASKS):
            self.state.addSubtask(f"pending {i}", "d")
        with mock.patch.object(self.orch, "authorBackfillBatch",
                               return_value=[{"title": "extra", "description": "d"}]) as a:
            added = self.orch._backfill(self.state, "arch", self.dash)
        self.assertEqual(added, 0)
        a.assert_not_called()             # cap reached -> don't even author

    def test_backfill_drops_placeholder_verify(self):
        batch = [{"title": "t", "description": "d", "layer": 3,
                  "verify": {"cmd": "python <ABSOLUTE path to x.py>", "expect": "exit_zero"}}]
        with mock.patch.object(self.orch, "authorBackfillBatch", return_value=batch):
            self.orch._backfill(self.state, "arch", self.dash)
        st = self.state.subtasks[0]
        self.assertIsNone(st.get("verify"))   # sanitizeVerify dropped the placeholder

    # ---- _continueAfterDrain ------------------------------------------
    def test_non_self_ref_run_breaks_on_drain(self):
        self.state.meta["is_self_referential"] = False
        cont, dry = self.orch._continueAfterDrain(self.state, "arch", self.dash, 0)
        self.assertFalse(cont)

    def test_deadline_passed_breaks(self):
        self.state.meta["deadline_at"] = _iso(-1)
        cont, _ = self.orch._continueAfterDrain(self.state, "arch", self.dash, 0)
        self.assertFalse(cont)

    def test_under_15_min_left_breaks(self):
        self.state.meta["deadline_at"] = _iso(0.1)   # ~6 min
        cont, _ = self.orch._continueAfterDrain(self.state, "arch", self.dash, 0)
        self.assertFalse(cont)

    def test_backfills_and_continues_with_time(self):
        with mock.patch.object(self.orch, "_backfill", return_value=3):
            cont, dry = self.orch._continueAfterDrain(self.state, "arch", self.dash, 1)
        self.assertTrue(cont)
        self.assertEqual(dry, 0)           # a productive backfill resets the dry counter

    def test_empty_backfill_twice_then_breaks(self):
        with mock.patch.object(self.orch, "_backfill", return_value=0):
            cont1, dry1 = self.orch._continueAfterDrain(self.state, "arch", self.dash, 0)
            cont2, dry2 = self.orch._continueAfterDrain(self.state, "arch", self.dash, dry1)
        self.assertTrue(cont1)             # first empty -> one retry
        self.assertEqual(dry1, 1)
        self.assertFalse(cont2)            # second empty -> finalize
        self.assertEqual(dry2, 2)


class TestPrGateDegraded(unittest.TestCase):
    """RC-5: night mode must NOT auto-ship a degraded run past a challenged adversary verdict."""
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._patch = mock.patch.object(config, "STATE_DIR", self.dir)
        self._patch.start()
        self.orch = Orchestrator()
        self.orch.obs = mock.Mock()
        self.state = TaskState.create("g", 1.0)

    def tearDown(self):
        self._patch.stop()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_degraded_when_selfmod_reverted(self):
        self.state.addNotification("selfmod_gate", "REVERTED (tests failed): ['orchestrator.py']")
        self.assertTrue(self.orch._runIsDegraded(self.state))

    def test_degraded_when_majority_failed(self):
        self.state.addSubtask("a", "d"); self.state.addSubtask("b", "d"); self.state.addSubtask("c", "d")
        self.state.updateSubtask("st-001", status="done")
        self.state.updateSubtask("st-002", status="failed")
        self.state.updateSubtask("st-003", status="failed")
        self.assertTrue(self.orch._runIsDegraded(self.state))   # 1/3 done < half

    def test_healthy_run_not_degraded(self):
        self.state.addSubtask("a", "d"); self.state.updateSubtask("st-001", status="done")
        self.assertFalse(self.orch._runIsDegraded(self.state))

    def test_night_mode_holds_pr_for_degraded_run(self):
        self.state.addNotification("selfmod_gate", "REVERTED (tests failed): ['config.py']")
        review = {"verdict": "challenged", "concerns": ["broke core"]}
        with mock.patch.object(config, "NIGHT_MODE", True), \
                mock.patch.object(config, "ADVERSARY_PR_HOLD_ENABLED", True):
            create, reason = self.orch._prGate(review, auto_pr=True, state=self.state)
        self.assertFalse(create)
        self.assertIn("HOLD", reason)

    def test_night_mode_ships_healthy_challenged_run(self):
        self.state.addSubtask("a", "d"); self.state.updateSubtask("st-001", status="done")
        review = {"verdict": "challenged", "concerns": ["minor"]}
        with mock.patch.object(config, "NIGHT_MODE", True), \
                mock.patch.object(config, "ADVERSARY_PR_HOLD_ENABLED", True):
            create, _ = self.orch._prGate(review, auto_pr=True, state=self.state)
        self.assertTrue(create)   # night mode + healthy + challenged -> ship (hands-off)


if __name__ == "__main__":
    unittest.main()
