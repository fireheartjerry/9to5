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


class TestNonLoopbackWarning(unittest.TestCase):
    """BUG-013: TLS verification is disabled (verify=False) for the Obsidian REST client --
    that's only safe against 127.0.0.1. A misconfigured non-loopback OBSIDIAN_BASE_URL must at
    least surface a warning rather than silently disabling cert checks against a network host."""

    def setUp(self):
        import memory.obsidian as ob
        self.ob = ob
        self._orig = ob._warned_non_loopback
        ob._warned_non_loopback = False

    def tearDown(self):
        self.ob._warned_non_loopback = self._orig

    def test_loopback_url_does_not_warn(self):
        with mock.patch.object(self.ob.LOG, "warning") as warn:
            self.ob._warnIfNonLoopback("http://127.0.0.1:27124")
            self.ob._warnIfNonLoopback("http://localhost:27124")
        warn.assert_not_called()

    def test_non_loopback_url_warns_once(self):
        with mock.patch.object(self.ob.LOG, "warning") as warn:
            self.ob._warnIfNonLoopback("https://obsidian.example.com:27124")
            self.ob._warnIfNonLoopback("https://obsidian.example.com:27124")
        warn.assert_called_once()


class TestRestPoolAtexitRegistration(unittest.TestCase):
    """BUG-017: atexit.register() for the REST pool shutdown must fire once PER PROCESS, not
    once per pool recreation -- otherwise tearing down and recreating the pool (flushRest() then
    a later write) stacks additional atexit registrations."""

    def setUp(self):
        import memory.obsidian as ob
        self.ob = ob
        self._orig_pool = ob._REST_POOL
        self._orig_registered = ob._REST_ATEXIT_REGISTERED
        ob._REST_POOL = None
        ob._REST_ATEXIT_REGISTERED = False

    def tearDown(self):
        if self.ob._REST_POOL is not None:
            self.ob._REST_POOL.shutdown(wait=False)
        self.ob._REST_POOL = self._orig_pool
        self.ob._REST_ATEXIT_REGISTERED = self._orig_registered

    def test_pool_recreation_registers_atexit_once(self):
        with mock.patch("memory.obsidian.atexit.register") as reg:
            self.ob._restPool()          # first creation -> registers
            self.ob.flushRest()          # tears the pool down (does NOT reset the flag)
            self.ob._restPool()          # recreation -> must NOT register again
        reg.assert_called_once()


if __name__ == "__main__":
    unittest.main()
