"""Tests for platform_core/ops/retention.py — the best-effort state GC sweep.

Retention prunes per-run blackboard/compaction artifacts (keep newest N + anything
younger than max_age_days) and ARCHIVES (never deletes) terminal-status task JSON.
It must never touch .py and never raise.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import config
from platform_core.ops import retention


_DAY = 86400


def _touch(path: Path, *, age_days: float, content: str = "{}") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    ts = time.time() - age_days * _DAY
    import os
    os.utime(path, (ts, ts))
    return path


def test_sweep_blackboard_keeps_recent_and_young(tmp_path):
    bb = tmp_path / "blackboard"
    # 15 files: index 0 = newest (age 0), index 14 = oldest (age 40d).
    for i in range(15):
        _touch(bb / f"{i:02d}.jsonl", age_days=i * 3)
    removed = retention.sweepBlackboard(directory=bb, keep_recent=10, max_age_days=14)
    survivors = sorted(p.name for p in bb.glob("*.jsonl"))
    # Newest 10 kept unconditionally; among the older 5, those younger than 14d also survive.
    assert "00.jsonl" in survivors and "09.jsonl" in survivors
    assert removed >= 1
    # Anything older than 14 days beyond the keep_recent window is gone.
    assert "14.jsonl" not in survivors  # age 42d, position 14


def test_sweep_never_touches_py(tmp_path):
    bb = tmp_path / "blackboard"
    _touch(bb / "keep.py", age_days=999, content="print('hi')")
    for i in range(12):
        _touch(bb / f"{i:02d}.jsonl", age_days=100)
    retention.sweepBlackboard(directory=bb, keep_recent=0, max_age_days=1)
    assert (bb / "keep.py").exists()  # .py is never removed


def test_sweep_compaction(tmp_path):
    comp = tmp_path / "compaction"
    for i in range(14):
        _touch(comp / f"ctx-{i}.txt", age_days=i * 5)
    retention.sweepCompaction(directory=comp, keep_recent=5, max_age_days=14)
    survivors = {p.name for p in comp.glob("ctx-*.txt")}
    assert "ctx-0.txt" in survivors  # newest kept
    assert "ctx-13.txt" not in survivors  # age 65d, beyond window


def test_archive_terminal_tasks_moves_not_deletes(tmp_path, monkeypatch):
    state = tmp_path / "tasks"
    archive = tmp_path / "archive"
    monkeypatch.setattr(config, "STATE_DIR", state, raising=False)
    monkeypatch.setattr(config, "ARCHIVE_DIR", archive, raising=False)
    old_done = _touch(state / "old.json", age_days=40,
                      content=json.dumps({"meta": {"status": "done"}}))
    _touch(state / "recent.json", age_days=1,
           content=json.dumps({"meta": {"status": "done"}}))
    _touch(state / "old_live.json", age_days=40,
           content=json.dumps({"meta": {"status": "running"}}))
    n = retention.archiveTerminalTasks(max_age_days=30)
    assert n == 1
    assert not old_done.exists()                       # moved out of the live dir
    assert (archive / "old.json").exists()             # archived, NOT deleted
    assert (state / "recent.json").exists()            # too young
    assert (state / "old_live.json").exists()          # non-terminal, never archived


def test_sweep_all_disabled_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RETENTION_ENABLED", False, raising=False)
    result = retention.sweepAll()
    assert result == {"enabled": False}


def test_sweep_missing_dir_is_safe(tmp_path):
    # No such directory -> 0 removed, no raise.
    assert retention.sweepBlackboard(directory=tmp_path / "nope", keep_recent=5, max_age_days=14) == 0


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
