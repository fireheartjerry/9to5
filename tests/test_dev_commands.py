"""Tests for agent-facing commands in tools/dev.py."""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import dev  # noqa: E402


def test_new_agent_commands_are_registered():
    assert {
        "ci-local",
        "slow-report",
        "heartbeat-test",
        "context-check",
        "iteration-health",
        "bench-iteration",
    } <= set(dev.COMMANDS)


def test_progress_env_sets_defaults_without_overriding(monkeypatch):
    monkeypatch.delenv("NINE_TO_FIVE_TEST_PROGRESS", raising=False)
    monkeypatch.setenv("NINE_TO_FIVE_TEST_HEARTBEAT_SECONDS", "9")

    env = dev._progress_env("3")

    assert env["NINE_TO_FIVE_TEST_PROGRESS"] == "1"
    assert env["NINE_TO_FIVE_TEST_HEARTBEAT_SECONDS"] == "9"


def test_run_tee_writes_markdown_report(tmp_path):
    out = tmp_path / "slow-test-report.md"
    rc = dev._run_tee(
        [sys.executable, "-c", "print('hello from slow report')"],
        out,
        env=dict(os.environ),
    )

    text = out.read_text(encoding="utf-8")
    assert rc == 0
    assert "Slow Test Report" in text
    assert "hello from slow report" in text


def test_bench_iteration_dry_run_lists_tasks(capsys):
    rc = dev.cmd_bench_iteration(["--dry-run"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "context-budget" in out
