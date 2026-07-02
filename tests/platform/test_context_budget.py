"""Tests for context-budget checks."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "tools"))
import context_budget  # noqa: E402


def test_context_budget_reports_core_surfaces():
    labels = {row["label"] for row in context_budget.measure()}

    assert {"CLAUDE.md", ".claude/rules", ".claude/skills"} <= labels


def test_context_budget_main_is_warning_by_default(monkeypatch):
    monkeypatch.setattr(context_budget, "measure", lambda: [{
        "label": "CLAUDE.md",
        "files": 1,
        "lines": 999,
        "chars": 999,
        "max_lines": 1,
        "max_chars": 1,
        "ok": False,
    }])

    assert context_budget.main([]) == 0
    assert context_budget.main(["--strict"]) == 1
