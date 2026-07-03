"""Tests for tools.claude_statusline."""
from __future__ import annotations

import io
import sys

sys.path.insert(0, "tools")
import claude_statusline  # noqa: E402


def test_statusline_formats_payload_and_git_state(monkeypatch, capsys):
    monkeypatch.setattr(sys, "stdin", io.StringIO('{"model":"opus","cost_usd":1.2345}'))
    monkeypatch.setattr(claude_statusline.claude_metrics, "git_state", lambda: {
        "dirty": True,
        "changed_files": 3,
        "branch": "feature",
    })

    assert claude_statusline.main() == 0
    assert capsys.readouterr().out.strip() == "9TO5 opus $1.234 | feature +3"
