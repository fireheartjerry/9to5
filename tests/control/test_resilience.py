"""Unit tests for the run supervisor / resilience layer (the 9->5 promise)."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

import config
import platform_core.runtime.resilience as resilience
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

    def test_returned_crashed_status_is_retried(self):
        # runFull catches its own crash and RETURNS a non-terminal 'crashed' status (it does not
        # raise). The supervisor must treat that as recoverable and resume, not stop.
        state = TaskState.create("g", 1.0)
        calls = {"n": 0}

        def run_fn(st):
            calls["n"] += 1
            if calls["n"] < 3:
                st.setStatus("crashed", blocked_reason="boom")   # persisted, NON-terminal
                return {"status": "crashed"}
            st.setStatus("done")
            return {"status": "done"}

        out = resilience.run_with_recovery(run_fn, state, reload_state=lambda t: state,
                                           sleep=lambda s: None)
        self.assertEqual(out["status"], "done")
        self.assertEqual(calls["n"], 3, "a returned 'crashed' status was not auto-resumed")

    def test_returned_blocked_status_is_terminal(self):
        # 'blocked' is the give-up status (e.g. restart budget exhausted) and MUST stay terminal so
        # the supervisor stops -- it must not be retried like 'crashed'.
        state = TaskState.create("g", 1.0)
        calls = {"n": 0}

        def run_fn(st):
            calls["n"] += 1
            st.setStatus("blocked", blocked_reason="gave up")
            return {"status": "blocked"}

        out = resilience.run_with_recovery(run_fn, state, reload_state=lambda t: state,
                                           sleep=lambda s: None)
        self.assertEqual(out["status"], "blocked")
        self.assertEqual(calls["n"], 1, "terminal 'blocked' was wrongly retried")

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


class _FakeBus:
    """Minimal ControlBus stand-in: abort flag flips after `after` isAbort() polls."""

    def __init__(self, abort=False):
        self.abort = abort

    def isAbort(self):
        return self.abort


class TestAbortSafeRecovery(unittest.TestCase):
    """Operator abort must survive a crashed run: the bus flag persists independently of
    task JSON, so a failed 'aborted' save can never be auto-RESUMED as a 'crash'."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        mock.patch.object(config, "STATE_DIR", self.dir).start()
        mock.patch.object(config, "RUN_MAX_RESTARTS", 5).start()

    def tearDown(self):
        mock.patch.stopall()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_crash_with_bus_abort_is_finalized_not_resumed(self):
        state = TaskState.create("g", 1.0)
        bus = _FakeBus(abort=False)
        calls = {"n": 0}

        def run_fn(st):
            calls["n"] += 1
            bus.abort = True                      # operator abort lands mid-run...
            raise RuntimeError("state save failed; abort persisted only on the bus")

        out = resilience.run_with_recovery(run_fn, state, reload_state=lambda t: state,
                                           sleep=lambda s: None, bus=bus)
        self.assertEqual(out["status"], "aborted")
        self.assertEqual(calls["n"], 1, "run_fn was re-invoked despite an operator abort")
        self.assertEqual(state.meta["status"], "aborted")

    def test_preexisting_abort_prevents_any_invocation(self):
        state = TaskState.create("g", 1.0)
        run_fn = mock.Mock()
        out = resilience.run_with_recovery(run_fn, state, reload_state=lambda t: state,
                                           sleep=lambda s: None, bus=_FakeBus(abort=True))
        self.assertEqual(out["status"], "aborted")
        run_fn.assert_not_called()

    def test_broken_bus_never_kills_recovery(self):
        state = TaskState.create("g", 1.0)

        class _BrokenBus:
            def isAbort(self):
                raise OSError("bus file unreadable")

        def run_fn(st):
            st.meta["status"] = "done"
            return {"status": "done"}

        out = resilience.run_with_recovery(run_fn, state, reload_state=lambda t: state,
                                           sleep=lambda s: None, bus=_BrokenBus())
        self.assertEqual(out["status"], "done")


class TestReloadStateStrikes(unittest.TestCase):
    """reload_state failures must be diagnosed, not swallowed: 3 consecutive strikes end
    the run with a distinct 'state file unreadable' reason instead of burning the whole
    restart budget blind."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        mock.patch.object(config, "STATE_DIR", self.dir).start()
        mock.patch.object(config, "RUN_MAX_RESTARTS", 50).start()

    def tearDown(self):
        mock.patch.stopall()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_three_reload_failures_finalize_with_distinct_reason(self):
        state = TaskState.create("g", 1.0)
        calls = {"run": 0, "reload": 0}

        def run_fn(st):
            calls["run"] += 1
            raise RuntimeError("crash")

        def bad_reload(task_id):
            calls["reload"] += 1
            raise OSError("corrupt json")

        with self.assertLogs("9to5.resilience", level="WARNING") as logs:
            out = resilience.run_with_recovery(run_fn, state, reload_state=bad_reload,
                                               sleep=lambda s: None, bus=_FakeBus())
        self.assertEqual(out["status"], "blocked")
        self.assertIn("state file unreadable", out["reason"])
        self.assertIn("corrupt json", out["reason"])
        self.assertEqual(calls["reload"], 3, "did not stop at the 3-strike streak")
        self.assertTrue(any("reload_state failed (strike" in m for m in logs.output),
                        f"no per-strike diagnostics logged: {logs.output}")

    def test_reload_strike_streak_resets_on_success(self):
        state = TaskState.create("g", 1.0)
        calls = {"run": 0, "reload": 0}

        def run_fn(st):
            calls["run"] += 1
            if calls["run"] >= 4:
                st.meta["status"] = "done"
                return {"status": "done"}
            raise RuntimeError("crash")

        def flaky_reload(task_id):
            calls["reload"] += 1
            if calls["reload"] % 2 == 1:          # fail, succeed, fail, succeed...
                raise OSError("transient")
            return state

        out = resilience.run_with_recovery(run_fn, state, reload_state=flaky_reload,
                                           sleep=lambda s: None, bus=_FakeBus())
        self.assertEqual(out["status"], "done", "an intermittent reload failure was fatal")


class TestNoBytecodeReload(unittest.TestCase):
    def test_no_importlib_reload_in_resilience_source(self):
        # In-process restart must keep the pinned bytecode; self-edits adopt only on a
        # fresh process. A reload would re-enter edited code incoherently.
        src = Path(resilience.__file__).read_text(encoding="utf-8")
        self.assertNotIn("importlib.reload", src)
