"""Tests for knowledge capability compression."""
from __future__ import annotations

from platform_core.knowledge_base import compress


def test_capability_cache_and_injection(monkeypatch):
    monkeypatch.setattr(compress, "_CAPABILITIES", "")
    compress.setCapabilities("skill: test")

    injected = compress.injectCapabilities("SYSTEM")

    assert compress.getCapabilities() == "skill: test"
    assert "CLAUDE CODE CAPABILITIES" in injected
    assert "SYSTEM" in injected


def test_compress_for_injection_includes_local_skills():
    out = compress.compressForInjection(
        "## Heading",
        {"skills": [{"name": "review", "description": "Review code", "desc_trusted": True}]},
        {},
        max_chars=1200,
    )

    assert "review: Review code" in out
    assert "Effort levels" in out
