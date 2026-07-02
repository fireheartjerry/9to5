"""SIE maintenance lock must reclaim an ORPHANED lock (owner PID dead) immediately, not wait for
the 1h staleness window -- maintenance runs on a daemon thread, so a process exiting mid-pass
would otherwise block all future maintenance for an hour."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from learning import sie


class TestSieLock(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._p = mock.patch.object(config, "CONTROL_DIR", self.dir)
        self._p.start()

    def tearDown(self):
        self._p.stop()

    def test_orphaned_lock_with_dead_owner_is_reclaimed(self):
        lp = sie._lock_path()
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text("999999999", encoding="utf-8")   # implausible -> definitely-dead PID
        got = sie._acquire_lock()
        self.assertIsNotNone(got, "did not reclaim a lock owned by a dead PID")
        self.assertEqual(lp.read_text(encoding="utf-8").strip(), str(os.getpid()))

    def test_lock_held_by_live_owner_is_not_stolen(self):
        lp = sie._lock_path()
        lp.parent.mkdir(parents=True, exist_ok=True)
        lp.write_text(str(os.getpid()), encoding="utf-8")   # our own pid == alive
        self.assertIsNone(sie._acquire_lock(), "stole a lock held by a live process")
