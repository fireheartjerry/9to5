"""Tests for platform_core.core.git_io."""
from __future__ import annotations

import subprocess

from platform_core.core import git_io


def test_run_git_disables_terminal_prompts(monkeypatch, tmp_path):
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        calls["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="true\n", stderr="")

    monkeypatch.setattr(git_io.subprocess, "run", fake_run)

    result = git_io.runGit("status", cwd=tmp_path, timeout=7)

    assert result.returncode == 0
    assert calls["cmd"] == ["git", "status"]
    assert calls["kwargs"]["stdin"] is subprocess.DEVNULL
    assert calls["kwargs"]["timeout"] == 7
    assert calls["kwargs"]["env"]["GIT_TERMINAL_PROMPT"] == "0"


def test_gate_commands_returns_mutable_copies():
    commands = git_io.gateCommands("repo_checks")
    commands[0].append("mutated")

    assert "mutated" not in git_io.gateCommands("repo_checks")[0]
