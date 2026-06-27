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
        self.assertEqual(errors, [])

    def test_no_lost_update_when_sidecar_lock_is_bypassed(self):
        """When the cross-process O_EXCL sidecar is bypassed (timeout/orphaned holder), an in-process
        lock must STILL serialize same-process writers so no field update is silently clobbered --
        otherwise a queued Abort or approve/reject decision can be lost and the run never stops."""
        import contextlib
        import control

        @contextlib.contextmanager
        def _bypassed(*_a, **_k):
            yield False   # simulate _fileLock giving up without holding the lock

        bus = ControlBus("lost-update")
        n = 24
        barrier = threading.Barrier(n)

        def worker(i: int) -> None:
            b = ControlBus("lost-update")
            barrier.wait()           # maximize the interleave on the unguarded RMW
            if i == 0:
                b.requestAbort()
            b.decide(f"gate{i}", "approve")   # each thread sets a DISTINCT key

        with mock.patch.object(control, "_fileLock", _bypassed):
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
            for t in threads:
                t.start()
            for t in threads:
                t.join(timeout=20)

        final = ControlBus("lost-update").load()
        self.assertTrue(final["abort"], "abort was silently lost under a bypassed sidecar lock")
        missing = [f"gate{i}" for i in range(n) if final["decisions"].get(f"gate{i}") != "approve"]
        self.assertEqual(missing, [], f"decisions lost to a clobbering RMW: {missing}")
        # the file is still valid JSON after the storm
        self.assertIsInstance(bus.load(), dict)

    def test_pushop_dedups_identical_ops(self):
        """The gateway bot and the in-run poller both push the SAME op for one Discord message; an
        identical op already queued must not be duplicated (one '!add' must not create two subtasks)."""
        bus = ControlBus("op-dedup")
        bus.pushOp({"op": "add", "title": "x"})
        bus.pushOp({"op": "add", "title": "x"})   # duplicate of the same message
        self.assertEqual(len(bus.drainOps()), 1)
        # distinct ops are all kept
        bus.pushOp({"op": "add", "title": "a"})
        bus.pushOp({"op": "skip", "subtask_id": "st-003"})
        self.assertEqual(len(bus.drainOps()), 2)

    def test_clearForRunStart_preserves_user_control(self):
        """A fresh run resets only the run cursor; an abort/pause/decision the user issued during the
        pre-run elaboration window must survive (a full clear() silently dropped it)."""
        bus = ControlBus("clear-start")
        bus.requestAbort()
        bus.requestPause()
        bus.decide("plan", "approve")
        bus.pushOp({"op": "add", "title": "x"})
        bus.setSeen("999")
        bus.setPendingGate("pre_pr")
        bus.clearForRunStart()
        d = bus.load()
        self.assertTrue(d["abort"], "abort issued during elaboration was wiped")
        self.assertTrue(d["pause"], "pause issued during elaboration was wiped")
        self.assertEqual(d["decisions"]["plan"], "approve")
        self.assertEqual(d["plan_ops"], [])          # run-cursor reset
        self.assertIsNone(d["seen_discord_id"])       # run-cursor reset
        self.assertIsNone(d["pending_gate"])          # run-cursor reset

    def test_corrupt_bus_rebuilds_so_abort_still_lands(self):
        """A persistently corrupt bus file must NOT permanently no-op mutations -- otherwise an
        aborting run could never stop. The mutation rebuilds from blank and lands."""
        bus = ControlBus("corrupt-task")
        bus.path.write_text("{ not valid json ::::::", encoding="utf-8")   # corrupt the file
        bus.requestAbort()
        self.assertTrue(ControlBus("corrupt-task").isAbort(), "abort lost on a corrupt bus")
        self.assertIsInstance(ControlBus("corrupt-task").load(), dict)
        # no temp files were left behind
        self.assertEqual(list(self.dir.glob("*.tmp")), [])


if __name__ == "__main__":
    unittest.main()
