"""Regression test for BUG-007: drainOps() must use the same strict read _mutate() uses, so a
transient read failure (Windows sharing violation, torn read) never clobbers queued plan_ops --
it previously called the tolerant self.load() first, which fabricates a blank bus on ANY read
failure, and the following (possibly premature) write would wipe out ops a bot/web pushed."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from platform_core.runtime.control import ControlBus, _CorruptBus


class TestDrainOpsStrictRead(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._patch = mock.patch.object(config, "CONTROL_DIR", self.dir)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_transient_read_failure_preserves_queued_ops(self):
        bus = ControlBus("t1")
        bus.pushOp({"cmd": "add", "title": "x"})

        with mock.patch.object(ControlBus, "_readRaw", side_effect=OSError("transient")):
            drained = bus.drainOps()
        self.assertEqual(drained, [], "a transient read failure must drain nothing, not raise")

        # The queued op must still be there for the NEXT (successful) drain -- proving the
        # transient failure did not clobber it via a premature blank-bus write.
        self.assertEqual(len(bus.drainOps()), 1, "queued op was lost after a transient read failure")

    def test_corrupt_bus_drains_nothing_without_raising(self):
        bus = ControlBus("t2")
        bus.pushOp({"cmd": "add", "title": "y"})

        with mock.patch.object(ControlBus, "_readRaw", side_effect=_CorruptBus("bad json")):
            drained = bus.drainOps()
        self.assertEqual(drained, [], "a corrupt bus must drain nothing, not raise")

    def test_normal_drain_still_clears_ops(self):
        bus = ControlBus("t3")
        bus.pushOp({"cmd": "add", "title": "z"})
        self.assertEqual(len(bus.drainOps()), 1)
        self.assertEqual(bus.drainOps(), [], "ops must be cleared after a successful drain")


if __name__ == "__main__":
    unittest.main()
