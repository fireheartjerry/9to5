"""Regression test for the ControlBus concurrent-write race: a shared temp filename made
two simultaneous writers collide on os.replace (FileNotFoundError). The bus is explicitly
multi-writer (run + Discord bot + web dashboard), so this must be safe under contention."""
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

import config
from control import ControlBus


class TestConcurrentWrites(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._patch = mock.patch.object(config, "CONTROL_DIR", self.dir)
        self._patch.start()

    def tearDown(self):
        self._patch.stop()

    def test_many_threads_hammering_the_bus_never_raise(self):
        bus = ControlBus("race-task")
        errors: list[Exception] = []

        def worker(n: int) -> None:
            b = ControlBus("race-task")   # each "process" opens its own handle (same file)
            try:
                for i in range(40):
                    if n % 3 == 0:
                        b.requestPause(); b.clearPause()
                    elif n % 3 == 1:
                        b.pushOp({"op": "add", "title": f"{n}-{i}"})
                    else:
                        b.setSeen(f"{n}-{i}")
                        b.drainOps()
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(n,)) for n in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=20)
        self.assertEqual(errors, [], f"concurrent ControlBus writes raised: {errors}")
        # the file is still valid JSON after the storm
        self.assertIsInstance(bus.load(), dict)
        # no temp files were left behind
        self.assertEqual(list(self.dir.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
