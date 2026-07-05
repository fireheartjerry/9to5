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


def test_run_tool_pins_utf8_decoding(monkeypatch, tmp_path):
    """REGRESSION: runTool MUST pin encoding='utf-8', errors='replace'. Without it, text
    mode decodes child stdout with the OS default (cp1252 on Windows), and a git/gh diff
    byte undefined in cp1252 (0x8f/0x9d) crashes the subprocess reader thread and loses the
    output. Mirrors the hardening already in agents/verification.py."""
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(git_io.subprocess, "run", fake_run)
    git_io.runTool(["git", "diff"], cwd=tmp_path)

    assert calls["kwargs"].get("encoding") == "utf-8"
    assert calls["kwargs"].get("errors") == "replace"


def test_run_tool_captures_non_cp1252_bytes_without_crashing(tmp_path):
    """REAL subprocess: a child emitting byte 0x8f (undefined in cp1252, e.g. inside a UTF-8
    git diff) must be captured, not lost. On Windows the pre-fix cp1252 path crashed the
    reader thread (UnicodeDecodeError) and dropped the output; utf-8+replace keeps it."""
    import sys

    child = [
        sys.executable,
        "-c",
        "import sys; sys.stdout.buffer.write(b'START\\x8fEND'); sys.stdout.flush()",
    ]
    result = git_io.runTool(child, cwd=tmp_path)

    assert result.stdout is not None, "child output was lost (reader thread crashed)"
    assert "START" in result.stdout and "END" in result.stdout
