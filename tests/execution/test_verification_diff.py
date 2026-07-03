"""Tests for diff-grounded verification helpers."""
from __future__ import annotations

import subprocess

from agents import verification_diff


def test_changed_files_parses_porcelain_and_renames(monkeypatch):
    monkeypatch.setattr(verification_diff.git_io, "runGit", lambda *a, **k: subprocess.CompletedProcess(
        ["git"], 0, stdout=" M a.py\n?? b.txt\nR  old.py -> new.py\n", stderr="",
    ))

    assert verification_diff.changedFiles(".") == {"a.py", "b.txt", "new.py"}


def test_declared_targets_require_changed_file_and_command_reference():
    ok, reason = verification_diff.checkDeclaredTargets(
        ".", ("src/a.py",), "python -m pytest tests/test_b.py", {"src/a.py"},
    )
    assert ok is False
    assert "acceptance command" in reason

    ok, _ = verification_diff.checkDeclaredTargets(".", ("src/a.py",), "python src/a.py", {"src/a.py"})
    assert ok is True
