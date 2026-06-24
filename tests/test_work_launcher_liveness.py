"""A LIVE orchestrator run must never be classed 'stale' (which mis-aborts it and lets a second
run double-spawn on the same repo). PID liveness is authoritative; mtime is only a legacy fallback."""
import os
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

import config
from notifications import work_launcher
from state.task import TaskState


class TestStaleLiveness(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._p = mock.patch.object(config, "STATE_DIR", self.dir)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def _task(self):
        st = TaskState.create("goal", 1.0)
        st.meta["status"] = "executing"
        st.save()
        return st

    def _age(self, st, seconds=100000):
        old = time.time() - seconds
        os.utime(st.path(), (old, old))

    def test_live_pid_not_stale_even_with_ancient_mtime(self):
        st = self._task()
        st.meta["run_pid"] = os.getpid()   # this process is alive
        st.save()
        self._age(st)                       # file untouched for ~27h
        self.assertFalse(work_launcher._isStale(st), "a live run was misread as stale")

    def test_dead_pid_is_stale(self):
        st = self._task()
        st.meta["run_pid"] = 999999999       # implausible -> definitely dead
        st.save()
        self.assertTrue(work_launcher._isStale(st))

    def test_no_pid_falls_back_to_mtime(self):
        st = self._task()
        st.meta.pop("run_pid", None)
        st.save()
        self._age(st)
        self.assertTrue(work_launcher._isStale(st), "legacy task with old mtime should be stale")


if __name__ == "__main__":
    unittest.main()
