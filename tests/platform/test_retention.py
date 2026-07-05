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
    old_done = _touch(state / "old.json", age_days=40, content=json.dumps({"meta": {"status": "done"}}))
    _touch(state / "recent.json", age_days=1, content=json.dumps({"meta": {"status": "done"}}))
    _touch(state / "old_live.json", age_days=40, content=json.dumps({"meta": {"status": "running"}}))
    n = retention.archiveTerminalTasks(max_age_days=30)
    assert n == 1
    assert not old_done.exists()  # moved out of the live dir
    assert (archive / "old.json").exists()  # archived, NOT deleted
    assert (state / "recent.json").exists()  # too young
    assert (state / "old_live.json").exists()  # non-terminal, never archived


def test_sweep_all_disabled_is_noop(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "RETENTION_ENABLED", False, raising=False)
    result = retention.sweepAll()
    assert result == {"enabled": False}


def test_sweep_missing_dir_is_safe(tmp_path):
    # No such directory -> 0 removed, no raise.
    assert retention.sweepBlackboard(directory=tmp_path / "nope", keep_recent=5, max_age_days=14) == 0


def test_sweep_hook_logs_truncates_past_cap(tmp_path):
    log = tmp_path / "hooks.log"
    # 20 one-line JSON records, each ~30 bytes -> well past a tiny cap.
    lines = [json.dumps({"i": i}) for i in range(20)]
    log.write_text("\n".join(lines) + "\n", encoding="utf-8")
    original_size = log.stat().st_size
    trimmed = retention.sweepHookLogs(path=log, max_bytes=100)
    assert trimmed > 0
    assert log.stat().st_size < original_size
    assert log.stat().st_size <= 100 + 40  # tail cap plus at most one partial-line's worth
    # The remaining content is intact, torn-line-free JSON (last lines survive).
    remaining = [ln for ln in log.read_text(encoding="utf-8").splitlines() if ln.strip()]
    for ln in remaining:
        json.loads(ln)  # never raises: no partial/torn line at the head
    assert remaining[-1] == lines[-1]  # newest record always survives


def test_sweep_hook_logs_under_cap_is_noop(tmp_path):
    log = tmp_path / "hooks.log"
    log.write_text('{"i": 0}\n', encoding="utf-8")
    assert retention.sweepHookLogs(path=log, max_bytes=1_000_000) == 0
    assert log.read_text(encoding="utf-8") == '{"i": 0}\n'


def test_sweep_hook_logs_missing_file_is_safe(tmp_path):
    assert retention.sweepHookLogs(path=tmp_path / "nope.log", max_bytes=100) == 0


def test_sweep_guard_alerts_truncates_past_cap(tmp_path):
    alerts = tmp_path / "guard_alerts.jsonl"
    lines = [json.dumps({"hook": "block_destructive", "i": i}) for i in range(20)]
    alerts.write_text("\n".join(lines) + "\n", encoding="utf-8")
    trimmed = retention.sweepGuardAlerts(path=alerts, max_bytes=100)
    assert trimmed > 0
    assert alerts.stat().st_size <= 100 + 60


def test_retention_byte_caps_are_defined_in_real_config():
    """REGRESSION: sweepHookLogs/sweepGuardAlerts read config.HOOKS_LOG_MAX_BYTES /
    config.GUARD_ALERTS_MAX_BYTES with NO fallback. They were never defined in config, so the
    live retention sweep crashed ("module 'config' has no attribute 'HOOKS_LOG_MAX_BYTES'",
    swallowed as "retention sweep failed (ignored)") and hooks.log / guard_alerts.jsonl grew
    unbounded. The sweep test below masked it with raising=False injection; this exercises the
    REAL config."""
    for name in ("HOOKS_LOG_MAX_BYTES", "GUARD_ALERTS_MAX_BYTES"):
        assert hasattr(config, name), f"config.{name} is not defined"
        val = getattr(config, name)
        assert isinstance(val, int) and val > 0, f"config.{name} = {val!r}"


def test_sweep_hook_and_guard_logs_use_real_config_defaults(tmp_path, monkeypatch):
    """The sweeps must run against the REAL config default (attr NOT injected) without raising
    AttributeError -- the exact production failure mode."""
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    (log_dir / "hooks.log").write_text("x" * 200, encoding="utf-8")
    (log_dir / "guard_alerts.jsonl").write_text("y" * 200, encoding="utf-8")
    monkeypatch.setattr(config, "LOG_PATH", log_dir, raising=False)
    # Deliberately do NOT inject HOOKS_LOG_MAX_BYTES / GUARD_ALERTS_MAX_BYTES.
    assert retention.sweepHookLogs() >= 0
    assert retention.sweepGuardAlerts() >= 0


def test_sweep_all_includes_hook_log_trim(tmp_path, monkeypatch):
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    hooks_log = log_dir / "hooks.log"
    hooks_log.write_text("\n".join(json.dumps({"i": i}) for i in range(50)) + "\n", encoding="utf-8")
    monkeypatch.setattr(config, "LOG_PATH", log_dir, raising=False)
    monkeypatch.setattr(config, "HOOKS_LOG_MAX_BYTES", 50, raising=False)
    monkeypatch.setattr(config, "GUARD_ALERTS_MAX_BYTES", 50, raising=False)
    result = retention.sweepAll()
    assert result["enabled"] is True
    assert result["hooks_log_trimmed"] > 0
    assert hooks_log.stat().st_size <= 50 + 40


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
