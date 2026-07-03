"""Heartbeat liveness matrix: fresh / stale / pid-alive / pid-dead / absent, plus the
throttled run-loop writer and the gateway-bot twin. Dirs are isolated by conftest."""
import os
import time
import uuid

import config
from platform_core.core import fsio
from platform_core.runtime import heartbeat as hb


def _tid() -> str:
    return f"hb-{uuid.uuid4().hex[:8]}"   # unique per test: module seq/throttle state is per-name


def _writeRaw(name, *, ts, pid):
    fsio.atomicWriteJson(hb.heartbeatPath(name), {"name": name, "pid": pid, "seq": 1, "ts": ts})


DEAD_PID = 999999999   # implausible -> definitely dead


def test_fresh_heartbeat_is_alive_even_with_dead_pid():
    tid = _tid()
    _writeRaw(tid, ts=time.time(), pid=DEAD_PID)
    assert hb.isRunAlive(tid) is True


def test_stale_heartbeat_dead_pid_is_dead():
    tid = _tid()
    _writeRaw(tid, ts=time.time() - 9999, pid=DEAD_PID)
    assert hb.isRunAlive(tid) is False


def test_stale_heartbeat_live_pid_is_alive():
    # A long subtask blocks the loop for minutes: heartbeat goes stale but the pid vouches.
    tid = _tid()
    _writeRaw(tid, ts=time.time() - 9999, pid=os.getpid())
    assert hb.isRunAlive(tid) is True


def test_no_heartbeat_falls_back_to_task_json_run_pid():
    tid = _tid()
    fsio.atomicWriteJson(config.STATE_DIR / f"{tid}.json",
                         {"task_id": tid, "meta": {"run_pid": os.getpid()}})
    assert hb.isRunAlive(tid) is True


def test_no_heartbeat_no_pid_is_dead():
    assert hb.isRunAlive(_tid()) is False


def test_write_then_clear_roundtrip():
    tid = _tid()
    hb.writeHeartbeat(tid)
    rec = hb.readHeartbeat(tid)
    assert rec is not None and rec["pid"] == os.getpid() and rec["seq"] == 1
    hb.clearHeartbeat(tid)
    assert hb.readHeartbeat(tid) is None


def test_beat_is_throttled_and_increments_seq():
    tid = _tid()
    assert hb.beat(tid) is True                    # first tick writes
    assert hb.beat(tid) is False                   # within the 10s window -> no write
    assert hb.beat(tid, interval_s=0.0) is True    # window elapsed -> writes again
    assert hb.readHeartbeat(tid)["seq"] == 2


def test_write_failure_never_raises(monkeypatch):
    monkeypatch.setattr(hb.fsio, "atomicWriteJson",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    hb.writeHeartbeat(_tid())   # must not raise


def test_bot_heartbeat_roundtrip():
    # No file + no pid on record -> dead; one presence-loop write -> alive.
    hb.clearHeartbeat(hb.BOT_NAME)
    assert hb.isBotAlive() is False
    hb.writeBotHeartbeat()
    assert hb.isBotAlive() is True


def test_garbage_heartbeat_file_degrades_to_pid_check():
    tid = _tid()
    hb.heartbeatPath(tid).parent.mkdir(parents=True, exist_ok=True)
    hb.heartbeatPath(tid).write_text("{not json", encoding="utf-8")
    assert hb.isRunAlive(tid) is False             # unreadable + no pid anywhere -> dead
