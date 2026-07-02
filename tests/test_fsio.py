"""Kernel unit suite for platform_core/core: fsio + jsonl_io + clock + git_io.

Covers the item-R4 acceptance list: concurrent atomic writes (threads AND processes,
no FileNotFoundError / torn file), updateJson corrupt-input .bak + warning, iterRecords
torn-tail tolerance (the adversary_trust regression), lock staleness/steal semantics,
bounded tool timeouts (the worktree hang regression), and RunClock deadline edges.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from platform_core.core import clock, fsio, git_io, jsonl_io

_ROOT = Path(__file__).resolve().parent.parent


# ---------------------------------------------------------------------------
# fsio: atomic writes
# ---------------------------------------------------------------------------

def test_atomic_write_concurrent_threads_and_processes_never_torn(tmp_path):
    target = tmp_path / "shared.json"
    errors: list[Exception] = []
    torn: list[str] = []
    stop = threading.Event()
    payloads = {f"t{i}": json.dumps({"writer": f"t{i}", "pad": "x" * 4000}) for i in range(8)}
    payloads.update({f"p{i}": json.dumps({"writer": f"p{i}", "pad": "y" * 4000}) for i in range(2)})

    def writer(wid: str) -> None:
        try:
            for _ in range(25):
                fsio.atomicWriteText(target, payloads[wid])
        except Exception as e:  # noqa: BLE001
            errors.append(e)

    def reader() -> None:
        valid = set(payloads.values())
        while not stop.is_set():
            try:
                t = target.read_text(encoding="utf-8")
            except (FileNotFoundError, PermissionError):
                continue
            if t and t not in valid:
                torn.append(t[:60])
            time.sleep(0.0005)

    # 2 real child processes hammering the SAME destination through the same kernel.
    code = (
        "import sys; sys.path.insert(0, sys.argv[1])\n"
        "from platform_core.core import fsio\n"
        "for _ in range(25):\n"
        "    fsio.atomicWriteText(sys.argv[2], sys.argv[3])\n"
    )
    procs = [subprocess.Popen([sys.executable, "-c", code, str(_ROOT), str(target),
                               payloads[f"p{i}"]]) for i in range(2)]
    threads = [threading.Thread(target=writer, args=(f"t{i}",)) for i in range(8)]
    readers = [threading.Thread(target=reader) for _ in range(2)]
    for r in readers:
        r.start()
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=30)
    rcs = [p.wait(timeout=60) for p in procs]
    stop.set()
    for r in readers:
        r.join(timeout=5)

    assert errors == [], f"concurrent atomic writes raised: {errors[:2]}"
    assert rcs == [0, 0], "a child-process writer crashed (FileNotFoundError race?)"
    assert torn == [], f"observed torn read(s): {torn[:1]}"
    assert json.loads(target.read_text(encoding="utf-8"))["writer"] in payloads
    assert list(tmp_path.glob("*.tmp")) == [], "left temp files behind"


def test_atomic_write_json_and_load_json_roundtrip(tmp_path):
    p = tmp_path / "sub" / "data.json"          # parent dir auto-created
    fsio.atomicWriteJson(p, {"a": 1, "b": [1, 2]})
    assert fsio.loadJson(p) == {"a": 1, "b": [1, 2]}


def test_load_json_missing_is_silent_default(tmp_path, caplog):
    with caplog.at_level(logging.WARNING, logger="core.fsio"):
        assert fsio.loadJson(tmp_path / "nope.json", default={"d": 1}) == {"d": 1}
    assert caplog.records == []                 # missing file: no warning


def test_load_json_corrupt_warns_and_returns_default(tmp_path, caplog):
    p = tmp_path / "bad.json"
    p.write_text("{not json!!!", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="core.fsio"):
        assert fsio.loadJson(p, default=None) is None
    assert any("unreadable" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# fsio: updateJson
# ---------------------------------------------------------------------------

def test_update_json_corrupt_input_preserved_as_bak_with_warning(tmp_path, caplog):
    p = tmp_path / "state.json"
    p.write_text("{torn-mid-write", encoding="utf-8")
    with caplog.at_level(logging.WARNING, logger="core.fsio"):
        out = fsio.updateJson(p, lambda d: {**d, "runs": 1}, default={})
    assert out == {"runs": 1}
    assert json.loads(p.read_text(encoding="utf-8")) == {"runs": 1}
    bak = tmp_path / "state.json.bak"
    assert bak.read_text(encoding="utf-8") == "{torn-mid-write"   # evidence preserved
    assert any("corrupt JSON preserved" in r.message for r in caplog.records)


def test_update_json_mutate_in_place_and_replacement(tmp_path):
    p = tmp_path / "d.json"

    def bump(d):
        d["n"] = d.get("n", 0) + 1              # in-place (returns None)

    assert fsio.updateJson(p, bump, default={}) == {"n": 1}
    assert fsio.updateJson(p, lambda d: {"n": d["n"] + 10}) == {"n": 11}   # replacement
    assert fsio.loadJson(p) == {"n": 11}


def test_update_json_with_lock_serializes_and_cleans_up(tmp_path):
    p = tmp_path / "locked.json"
    fsio.updateJson(p, lambda d: {"v": 1}, default={}, lock=True)
    assert fsio.loadJson(p) == {"v": 1}
    assert not (tmp_path / "locked.json.lock").exists()   # released after the write


# ---------------------------------------------------------------------------
# fsio: pid locks
# ---------------------------------------------------------------------------

def test_lock_fresh_is_never_stolen(tmp_path):
    lp = tmp_path / "x.lock"
    assert fsio.tryAcquireLock(lp) is True
    assert fsio.tryAcquireLock(lp) is False               # held + fresh -> refused


def test_lock_stale_by_age_is_stolen_after_restat(tmp_path):
    lp = tmp_path / "x.lock"
    lp.write_text("12345", encoding="utf-8")
    old = time.time() - 7200
    os.utime(lp, (old, old))
    assert fsio.tryAcquireLock(lp, stale_after=3600) is True
    assert lp.read_text(encoding="utf-8").strip() == str(os.getpid())   # we own it now


def test_lock_dead_owner_is_stolen_live_owner_is_not(tmp_path):
    lp = tmp_path / "x.lock"
    lp.write_text("999999999", encoding="utf-8")
    assert fsio.tryAcquireLock(lp, stale_after=3600, owner_alive=lambda pid: False) is True
    fsio.releaseLock(lp)
    lp.write_text(str(os.getpid()), encoding="utf-8")
    assert fsio.tryAcquireLock(lp, stale_after=3600, owner_alive=lambda pid: True) is False


def test_lock_unreadable_owner_is_conservatively_alive(tmp_path):
    lp = tmp_path / "x.lock"
    lp.write_text("garbage-not-a-pid", encoding="utf-8")
    # owner_alive is available but the pid can't be read -> never steal the unprovable.
    assert fsio.tryAcquireLock(lp, stale_after=3600, owner_alive=lambda pid: False) is False


def test_file_lock_context_manager_and_timeout(tmp_path):
    lp = tmp_path / "cm.lock"
    with fsio.fileLock(lp, timeout=2.0):
        assert lp.exists()
        with pytest.raises(TimeoutError):
            with fsio.fileLock(lp, timeout=0.2, poll=0.02):
                pass
    assert not lp.exists()                                # released on exit
    with fsio.fileLock(lp, timeout=2.0):                  # re-acquirable
        pass


# ---------------------------------------------------------------------------
# jsonl_io
# ---------------------------------------------------------------------------

def test_iter_records_torn_tail_keeps_history(tmp_path):
    p = tmp_path / "log.jsonl"
    for i in range(5):
        jsonl_io.appendRecord(p, {"i": i})
    with p.open("a", encoding="utf-8") as fh:
        fh.write('{"i": 5, "torn')                        # crash mid-append
    records, skipped = jsonl_io.iterRecords(p)
    assert [r["i"] for r in records] == [0, 1, 2, 3, 4]   # N-1 records survive
    assert skipped == 1


def test_iter_records_missing_file(tmp_path):
    assert jsonl_io.iterRecords(tmp_path / "nope.jsonl") == ([], 0)


def test_append_record_rotates_past_max_bytes(tmp_path):
    p = tmp_path / "audit.jsonl"
    for i in range(30):
        jsonl_io.appendRecord(p, {"i": i, "pad": "x" * 10}, max_bytes=100)
    assert (tmp_path / "audit.jsonl.1").exists()
    assert jsonl_io.readTail(p, 5)                         # still readable after rotation


def test_read_tail_returns_last_n_oldest_first(tmp_path):
    p = tmp_path / "t.jsonl"
    for i in range(10):
        jsonl_io.appendRecord(p, {"i": i})
    assert [r["i"] for r in jsonl_io.readTail(p, 3)] == [7, 8, 9]
    assert jsonl_io.readTail(tmp_path / "nope.jsonl", 3) == []


# ---------------------------------------------------------------------------
# clock
# ---------------------------------------------------------------------------

def test_now_iso_formats_are_seconds_precision_and_aware():
    utc = clock.nowIsoUtc()
    local = clock.nowIsoLocal()
    assert utc.endswith("+00:00")
    assert datetime.fromisoformat(utc).tzinfo is not None
    assert datetime.fromisoformat(local).tzinfo is not None


def test_parse_iso_and_elapsed_handle_naive_aware_and_garbage():
    assert clock.parseIso(None) is None
    assert clock.parseIso("not-a-date") is None
    aware = (datetime.now().astimezone() - timedelta(seconds=90)).isoformat()
    naive = (datetime.now() - timedelta(seconds=90)).isoformat()
    assert 85 <= clock.elapsedSecondsSince(aware) <= 120
    assert 85 <= clock.elapsedSecondsSince(naive) <= 120   # naive compared in its own frame
    assert clock.elapsedSecondsSince("garbage") == 0.0


def test_fmt_elapsed_and_elapsed_str():
    assert clock.fmtElapsed(42) == "42s"
    assert clock.fmtElapsed(5 * 60) == "5m"
    assert clock.fmtElapsed(2 * 3600 + 15 * 60) == "2h 15m"
    assert clock.fmtElapsed(-3) == "0s"
    assert clock.elapsedStr(None) == "—"
    assert clock.elapsedStr("not-a-date") == "—"
    future = (datetime.now() + timedelta(hours=1)).isoformat()
    assert clock.elapsedStr(future) == "0s"                # clamped, matches dashboard


def test_eta_str_paced_and_unknowable():
    started = (datetime.now().astimezone() - timedelta(minutes=10)).isoformat()
    assert clock.etaStr(started, done=1, total=2).startswith("~")
    assert clock.etaStr(started, done=0, total=5) == "—"
    assert clock.etaStr(started, done=5, total=5) == "—"
    assert clock.etaStr(None, done=1, total=2) == "—"


def test_run_clock_deadline_edges():
    now = datetime.now().astimezone()
    assert clock.RunClock(None).remainingSeconds() is None
    assert clock.RunClock(None).passed() is False
    assert clock.RunClock("garbage").passed() is False
    assert clock.RunClock(now.isoformat()).passed() is True            # exactly-now counts
    future = clock.RunClock((now + timedelta(hours=1)).isoformat())
    assert future.passed() is False
    assert 3500 <= future.remainingSeconds() <= 3600
    assert future.remainingHours() == pytest.approx(1.0, abs=0.05)
    past = clock.RunClock((now - timedelta(minutes=1)).isoformat())
    assert past.passed() is True
    assert past.remainingSeconds() < 0


# ---------------------------------------------------------------------------
# git_io
# ---------------------------------------------------------------------------

def test_run_tool_timeout_kills_hung_child():
    t0 = time.monotonic()
    with pytest.raises(subprocess.TimeoutExpired):
        git_io.runTool([sys.executable, "-c", "import time; time.sleep(30)"], timeout=1.5)
    assert time.monotonic() - t0 < 15, "hung child was not bounded by the timeout"


def test_run_git_never_prompts_and_reports_non_repo(tmp_path):
    r = git_io.runGit("rev-parse", "--is-inside-work-tree", cwd=tmp_path, timeout=30)
    assert r.returncode != 0                    # returned (no hang, no prompt), not raised
    ok, reason = git_io.gitPreflight(tmp_path, timeout=30)
    assert ok is False
    assert reason == "not a git repository"


def test_gate_commands_tiers_share_repo_checks_and_return_fresh_copies():
    repo = git_io.gateCommands("repo_checks")
    pre = git_io.gateCommands("pre_pr")
    assert pre[:3] == repo                      # pre_pr = repo checks + the fast suite
    assert len(pre) == len(repo) + 1
    assert "pytest" in " ".join(pre[-1])
    repo[0].append("MUTATED")                   # must not leak into the shared table
    assert git_io.gateCommands("repo_checks")[0][-1] != "MUTATED"
