"""Tests for Claude iteration telemetry helpers."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import claude_metrics  # noqa: E402


def test_record_hook_event_writes_compact_jsonl(tmp_path, monkeypatch):
    out = tmp_path / "turns.jsonl"
    monkeypatch.setattr(claude_metrics, "TURN_LOG", out)
    monkeypatch.setattr(claude_metrics, "git_state", lambda: {
        "branch": "test", "dirty": False, "changed_files": 0,
    })

    claude_metrics.record_hook_event("user_prompt_telemetry", {
        "session_id": "abc",
        "prompt": "hello",
        "tool_name": "Bash",
        "tool_input": {"command": "python -m pytest"},
    })

    row = json.loads(out.read_text(encoding="utf-8"))
    assert row["hook"] == "user_prompt_telemetry"
    assert row["session_id"] == "abc"
    assert row["prompt_chars"] == 5
    assert row["tool_command_len"] == len("python -m pytest")


def test_hooks_telemetry_tolerates_malformed_stdin():
    proc = subprocess.run(
        [sys.executable, "agents/hooks.py", "user_prompt_telemetry"],
        input="{not-json",
        cwd=Path(__file__).resolve().parent.parent,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert proc.returncode == 0


def test_statusline_prints_compact_state():
    proc = subprocess.run(
        [sys.executable, "tools/claude_statusline.py"],
        input=json.dumps({"model": "claude-test"}),
        cwd=Path(__file__).resolve().parent.parent,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert proc.returncode == 0
    assert "9TO5 claude-test" in proc.stdout
