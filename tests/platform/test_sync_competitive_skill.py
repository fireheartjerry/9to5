"""Tests for project-to-Codex competitive skill sync."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import sync_competitive_skill as syncer  # noqa: E402


def test_sync_copies_canonical_skill(tmp_path):
    target = syncer.sync(tmp_path)

    assert target == tmp_path / "competitive-systems"
    text = (target / "SKILL.md").read_text(encoding="utf-8")
    assert "Codeforces rating" in text
    assert (target / "references" / "ci.md").exists()
