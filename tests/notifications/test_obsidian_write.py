"""Unit tests for ObsidianClient.writeNote -- the disk fallback must always engage
and the method must NEVER raise into the run (its documented contract; a raise in
the orchestrator's post-completion note write would corrupt a finished subtask)."""
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from memory.obsidian import ObsidianClient


class TestWriteNote(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.client = ObsidianClient()
        self.client.disk_root = self.dir

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_disk_fallback_writes_when_rest_fails(self):
        with mock.patch("memory.obsidian.requests.put", side_effect=OSError("no net")):
            res = self.client.writeNote("tasks/x.md", "hello")
        self.assertTrue(res["ok"])
        self.assertEqual(res["via"], "disk")
        self.assertEqual((self.dir / "tasks" / "x.md").read_text(encoding="utf-8"), "hello")

    def test_never_raises_when_disk_also_fails(self):
        with mock.patch("memory.obsidian.requests.put", side_effect=OSError("no net")), \
                mock.patch.object(self.client, "_writeDisk", side_effect=OSError("disk full")):
            res = self.client.writeNote("tasks/x.md", "hello")
        self.assertFalse(res["ok"])
        self.assertEqual(res["via"], "none")
        self.assertIn("error", res)

    def test_async_returns_disk_immediately_without_blocking_on_rest(self):
        import config
        import memory.obsidian as ob

        rest_calls = {"n": 0}

        def slow_rest(*a, **k):                 # a REST PUT that would block the run
            rest_calls["n"] += 1
            raise OSError("vault busy")

        with mock.patch.object(config, "OBSIDIAN_ASYNC", True), \
                mock.patch.object(ob, "_restPut", side_effect=slow_rest):
            res = self.client.writeNote("tasks/y.md", "hi")     # returns from disk, not REST
            self.assertEqual(res["via"], "disk")
            self.assertEqual((self.dir / "tasks" / "y.md").read_text(encoding="utf-8"), "hi")
            ob.flushRest()                                       # drain the background sync
        self.assertEqual(rest_calls["n"], 1)                     # REST still attempted, off hot path

    def test_sync_mode_is_rest_first(self):
        import config
        with mock.patch.object(config, "OBSIDIAN_ASYNC", False), \
                mock.patch("memory.obsidian.requests.put") as put:
            put.return_value = mock.Mock(status_code=200)
            res = self.client.writeNote("tasks/z.md", "hi")
        self.assertEqual(res["via"], "rest")
