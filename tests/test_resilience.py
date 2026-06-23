"""Unit tests for the run supervisor / resilience layer (the 9->5 promise)."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import config
import resilience
from state.task import TaskState


class TestTimeAndProgress(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        mock.patch.object(config, "STATE_DIR", self.dir).start()

    def tearDown(self):
        mock.patch.stopall()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_remaining_and_deadline(self):
        future = TaskState.create("g", 1.0)            # 1h ahead
        self.assertGreater(resilience.remaining_seconds(future), 0)
        self.assertFalse(resilience.deadline_passed(future))
        past = TaskState.create("g", 1.0)
        past.meta["deadline_at"] = (datetime.now().astimezone() - timedelta(hours=1)).isoformat()
        self.assertTrue(resilience.deadline_passed(past))

    def test_is_terminal(self):
        s = TaskState.create("g", 1.0)
        self.assertFalse(resilience.is_terminal(s))
        s.meta["status"] = "done"
        self.assertTrue(resilience.is_terminal(s))

    def test_stall_detection(self):
        s = TaskState.create("g", 1.0)
        s.meta["started_at"] = (datetime.now().astimezone() - timedelta(hours=2)).isoformat()
        self.assertTrue(resilience.is_stalled(s, max_idle_seconds=600))
        s.meta["started_at"] = datetime.now().astimezone().isoformat()
        self.assertFalse(resilience.is_stalled(s, max_idle_seconds=600))

    def test_pick_resume_task(self):
        done = TaskState.create("done goal", 1.0)
        done.meta["status"] = "complete"
        done.save()
        active = TaskState.create("active goal", 1.0)
        active.save()
        self.assertEqual(resilience.pick_resume_task(), active.task_id)
        active.setStatus("done")
        self.assertIsNone(resilience.pick_resume_task())


class TestRunWithRecovery(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        mock.patch.object(config, "STATE_DIR", self.dir).start()
        mock.patch.object(config, "RUN_MAX_RESTARTS", 5).start()

    def tearDown(self):
        mock.patch.stopall()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_clean_run_no_restart(self):
        state = TaskState.create("g", 1.0)
        calls = {"n": 0}

        def run_fn(st):
            calls["n"] += 1
            st.meta["status"] = "done"
            return {"status": "done"}

        out = resilience.run_with_recovery(run_fn, state, reload_state=lambda t: state,
                                           sleep=lambda s: None)
        self.assertEqual(out["status"], "done")
        self.assertEqual(calls["n"], 1)

    def test_crash_then_resume_succeeds(self):
        state = TaskState.create("g", 1.0)
        calls = {"n": 0}

        def run_fn(st):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("boom mid-run")
            st.meta["status"] = "done"
            return {"status": "done"}

        out = resilience.run_with_recovery(run_fn, state, reload_state=lambda t: state,
                                           sleep=lambda s: None)
        self.assertEqual(out["status"], "done")
        self.assertEqual(calls["n"], 2)          # crashed once, auto-resumed, finished

    def test_deadline_stops_restart_loop(self):
        state = TaskState.create("g", 1.0)
        state.meta["deadline_at"] = (datetime.now().astimezone() - timedelta(minutes=1)).isoformat()

        def run_fn(st):
            raise RuntimeError("always crashes")

        out = resilience.run_with_recovery(run_fn, state, reload_state=lambda t: state,
                                           sleep=lambda s: None)
        self.assertEqual(out["reason"], "deadline")
        self.assertIn(state.meta["status"], ("partial", "done", "complete", "aborted", "blocked", "failed"))

    def test_restart_budget_exhausted_blocks(self):
        state = TaskState.create("g", 1.0)
        with mock.patch.object(config, "RUN_MAX_RESTARTS", 2):
            out = resilience.run_with_recovery(
                lambda st: (_ for _ in ()).throw(RuntimeError("nope")),
                state, reload_state=lambda t: state, sleep=lambda s: None)
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(out["reason"], "max_restarts")


if __name__ == "__main__":
    unittest.main()
