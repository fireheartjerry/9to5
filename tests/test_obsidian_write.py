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


if __name__ == "__main__":
    unittest.main()
