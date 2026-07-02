"""ControlBus over SQLite: the bus is explicitly multi-writer (orchestrator run, Discord
gateway bot, web dashboard, terminal thread), so it must stay correct under thread AND
real-process contention -- no lost abort, no lost/duplicated op, no lost decision. The
old JSON-file bus needed sidecar locks and identity dedup; here BEGIN IMMEDIATE
transactions and UNIQUE(task_id, source_msg_id) make those properties structural."""
import multiprocessing
import threading
import time
import unittest
from pathlib import Path

import pytest

from platform_core.runtime import control_store
from platform_core.runtime.control import ControlBus


class TestConcurrentWrites(unittest.TestCase):
    def test_many_threads_hammering_the_bus_never_raise(self):
        ControlBus("race-task")
        errors: list[Exception] = []

        def worker(n: int) -> None:
            b = ControlBus("race-task")   # each "process" opens its own handle (same db)
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
            t.join(timeout=30)
        self.assertEqual(errors, [])

    def test_no_lost_update_under_thread_contention(self):
        """N threads mutate DISTINCT keys simultaneously plus one abort: every write must
        land (the old file bus could clobber a queued abort/decision in a bypassed-lock
        read-modify-write window; SQLite transactions make that impossible)."""
        n = 24
        barrier = threading.Barrier(n)

        def worker(i: int) -> None:
            b = ControlBus("lost-update")
            barrier.wait()           # maximize the interleave
            if i == 0:
                b.requestAbort()
            b.decide(f"gate{i}", "approve")   # each thread sets a DISTINCT key

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        final = ControlBus("lost-update").load()
        self.assertTrue(final["abort"], "abort was silently lost under contention")
        missing = [f"gate{i}" for i in range(n) if final["decisions"].get(f"gate{i}") != "approve"]
        self.assertEqual(missing, [], f"decisions lost to a clobbering write: {missing}")

    def test_no_op_lost_or_duplicated_while_draining(self):
        """Pushers race a concurrent drainer: every pushed op is drained exactly once."""
        bus = ControlBus("drain-race")
        n_pushers, per = 6, 30
        drained: list[dict] = []
        stop = threading.Event()

        def pusher(n: int) -> None:
            b = ControlBus("drain-race")
            for i in range(per):
                b.pushOp({"op": "add", "title": f"{n}-{i}"})

        def drainer() -> None:
            b = ControlBus("drain-race")
            while not stop.is_set():
                drained.extend(b.drainOps())

        d = threading.Thread(target=drainer)
        d.start()
        threads = [threading.Thread(target=pusher, args=(n,)) for n in range(n_pushers)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        stop.set()
        d.join(timeout=30)
        drained.extend(bus.drainOps())   # sweep anything still queued
        titles = [o["title"] for o in drained]
        self.assertEqual(len(titles), n_pushers * per, "an op was lost or duplicated")
        self.assertEqual(len(set(titles)), n_pushers * per, "an op was drained twice")

    def test_drain_returns_ops_in_push_order(self):
        bus = ControlBus("op-order")
        for i in range(10):
            bus.pushOp({"op": "add", "title": f"t{i}"})
        self.assertEqual([o["title"] for o in bus.drainOps()], [f"t{i}" for i in range(10)])

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


class TestSourceMsgDedup(unittest.TestCase):
    """R8 dedup semantics: keyed by the ORIGIN MESSAGE, not by op identity."""

    def test_same_source_msg_twice_is_one_op(self):
        """The gateway bot and the degraded REST poller ingest the SAME Discord message:
        one op, not two (UNIQUE(task_id, source_msg_id))."""
        bus = ControlBus("msg-dedup")
        bus.pushOp({"op": "add", "title": "x"}, source_msg_id="111")
        bus.pushOp({"op": "add", "title": "x"}, source_msg_id="111")
        self.assertEqual(len(bus.drainOps()), 1)

    def test_two_identical_messages_are_two_ops(self):
        """A user legitimately typing '!retry' twice (two message ids) retries twice --
        the old whole-op identity dedup swallowed the second one."""
        bus = ControlBus("msg-dedup2")
        bus.pushOp({"op": "retry"}, source_msg_id="201")
        bus.pushOp({"op": "retry"}, source_msg_id="202")
        self.assertEqual(len(bus.drainOps()), 2)

    def test_ops_without_source_id_never_dedup(self):
        """Web dashboard / terminal / launcher pushes carry no message id: identical
        bodies are all kept (NULLs are distinct under SQLite UNIQUE)."""
        bus = ControlBus("no-id")
        bus.pushOp({"op": "add", "title": "x"})
        bus.pushOp({"op": "add", "title": "x"})
        self.assertEqual(len(bus.drainOps()), 2)


# ---------------------------------------------------------------------------
# TRUE cross-process contention (multiprocessing spawn -> real OS processes)
# ---------------------------------------------------------------------------
def _procWorker(db_path: str, idx: int, per: int) -> None:
    """Real-process worker: hammer pushOp/flags on the SHARED db; worker 0 fires the abort
    mid-storm. Must run at module top level (spawn pickling)."""
    from platform_core.runtime import control_store as cs
    from platform_core.runtime.control import ControlBus as CB
    cs._DB_OVERRIDE = Path(db_path)
    bus = CB("xproc")
    for i in range(per):
        bus.pushOp({"op": "add", "title": f"p{idx}-{i}"})
        if idx == 0 and i == per // 2:
            bus.requestAbort()
        if i % 25 == 0:
            bus.setSeen(f"{idx}-{i}")


@pytest.mark.timeout(180)   # 2 spawn children re-import the platform; marginal under the 60s default
class TestCrossProcess(unittest.TestCase):
    def test_two_real_processes_never_lose_an_abort_or_an_op(self):
        """Two real OS processes hammer the bus while this process drains concurrently:
        the abort is always visible afterwards and every op is drained exactly once --
        the failure mode the old sidecar-lock bus could not exclude."""
        per = 200
        db = str(control_store._dbPath())
        # Touch the store so the db FILE exists before any child connects: a child seeing a
        # missing db would run the one-shot legacy migration against the REAL state/control/.
        ControlBus("xproc").isPaused()
        drained: list[dict] = []
        stop = threading.Event()

        def drainer() -> None:
            b = ControlBus("xproc")
            while not stop.is_set():
                drained.extend(b.drainOps())
                time.sleep(0.001)   # yield the core; a hot drain loop starves the spawn children

        d = threading.Thread(target=drainer)
        d.start()
        ctx = multiprocessing.get_context("spawn")
        procs = [ctx.Process(target=_procWorker, args=(db, idx, per)) for idx in range(2)]
        for p in procs:
            p.start()
        for p in procs:
            p.join(timeout=120)
        stop.set()
        d.join(timeout=30)
        self.assertTrue(all(p.exitcode == 0 for p in procs),
                        f"worker process failed: {[p.exitcode for p in procs]}")
        bus = ControlBus("xproc")
        drained.extend(bus.drainOps())
        titles = [o["title"] for o in drained]
        self.assertEqual(len(titles), 2 * per, "an op was lost across processes")
        self.assertEqual(len(set(titles)), 2 * per, "an op was duplicated across processes")
        self.assertTrue(bus.isAbort(), "the abort fired by a real process was lost")
