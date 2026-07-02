"""A LIVE orchestrator run must never be classed 'stale' (which mis-aborts it and lets a second
run double-spawn on the same repo). Liveness is heartbeat.isRunAlive -- heartbeat fresh OR
recorded pid alive; the old mtime heuristic is gone. Stale cleanup goes through the bus +
task_io.reapDeadRun, never a direct task-JSON write from the bot process."""
import os
import time
import unittest
from unittest import mock

import config
from notifications import work_launcher
from platform_core.core import fsio
from state.task import TaskState

DEAD_PID = 999999999   # implausible -> definitely dead


def _task(status="executing"):
    st = TaskState.create("goal", 1.0)
    st.meta["status"] = status
    st.save()
    return st


def _age(st, seconds=100000):
    old = time.time() - seconds
    os.utime(st.path(), (old, old))


class TestStaleLiveness(unittest.TestCase):
    def test_live_pid_not_stale_even_with_ancient_mtime(self):
        st = _task()
        st.meta["run_pid"] = os.getpid()   # this process is alive
        st.save()
        _age(st)                            # file untouched for ~27h
        self.assertFalse(work_launcher._isStale(st), "a live run was misread as stale")

    def test_created_status_live_pid_not_stale(self):
        # A still-initializing run (status 'created') stamps run_pid BEFORE the slow Ollama
        # elaboration, so even a multi-minute elaboration is NOT mis-declared stale.
        st = _task(status="created")
        st.meta["run_pid"] = os.getpid()
        st.save()
        _age(st, seconds=1000)
        self.assertFalse(work_launcher._isStale(st),
                         "a live still-elaborating run was misread as stale (double-spawn risk)")

    def test_fresh_heartbeat_not_stale_despite_dead_pid_and_old_mtime(self):
        # The heartbeat is authoritative when fresh: an old task-file mtime means nothing.
        st = _task()
        st.meta["run_pid"] = DEAD_PID
        st.save()
        _age(st)
        fsio.atomicWriteJson(config.HEARTBEAT_DIR / f"{st.task_id}.json",
                             {"pid": DEAD_PID, "seq": 3, "ts": time.time()})
        self.assertFalse(work_launcher._isStale(st),
                         "a heartbeat-fresh run was misread as stale")

    def test_dead_pid_is_stale(self):
        st = _task()
        st.meta["run_pid"] = DEAD_PID
        st.save()
        self.assertTrue(work_launcher._isStale(st))

    def test_no_pid_no_heartbeat_is_stale(self):
        st = _task()
        st.meta.pop("run_pid", None)
        st.save()
        self.assertTrue(work_launcher._isStale(st),
                        "a task with no liveness evidence at all should be stale")


class TestStaleReap(unittest.TestCase):
    """activeRun's stale path: bus abort + reapDeadRun -- NEVER a direct task-JSON write."""

    def test_stale_run_reaped_via_bus_and_escape_hatch(self):
        st = _task()
        st.meta["run_pid"] = DEAD_PID
        st.save()
        with mock.patch.object(work_launcher.commands, "resolveTargetTask", return_value=st), \
                mock.patch.object(TaskState, "setStatus",
                                  side_effect=AssertionError("bot wrote task JSON directly")):
            self.assertIsNone(work_launcher.activeRun())
        from platform_core.runtime.control import ControlBus
        bus = ControlBus(st.task_id)
        self.assertTrue(bus.isAbort(), "stale cleanup did not request abort on the bus")
        ops = bus.drainOps()
        self.assertTrue(any(o.get("op") == "mark_stale" for o in ops), f"no breadcrumb op: {ops}")
        self.assertEqual(TaskState.load(st.task_id).meta["status"], "aborted",
                         "dead run was not finalized through reapDeadRun")

    def test_live_run_never_reaped(self):
        st = _task()
        st.meta["run_pid"] = os.getpid()
        st.save()
        with mock.patch.object(work_launcher.commands, "resolveTargetTask", return_value=st):
            self.assertIs(work_launcher.activeRun(), st)
        self.assertEqual(TaskState.load(st.task_id).meta["status"], "executing")
