"""Tests for tools.codemod dry-run helpers."""
from __future__ import annotations

import sys

sys.path.insert(0, "tools")
import codemod  # noqa: E402


def test_usages_reports_symbol_with_repo_subset(capsys):
    rc = codemod.cmd_usages("test_brain", only="tools")

    out = capsys.readouterr()
    assert rc == 0
    assert "tools/dev.py:" in out.out
    assert "usage(s) of 'test_brain'" in out.err
