"""Tests for compact LLM navigation packets."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import llm_navigation  # noqa: E402


def _map() -> dict:
    return {"modules": {
        "tools.alpha": {"path": "tools/alpha.py", "purpose": "select tests", "exports": [{"name": "pick"}],
                        "depends_on": ["tools.beta"], "callers": [], "test": ["tests/platform/test_alpha.py"]},
        "tools.beta": {"path": "tools/beta.py", "purpose": "support", "exports": [{"name": "help"}],
                       "depends_on": [], "callers": ["tools.alpha"], "test": []},
    }}


def test_projection_preserves_navigation_contract_fields():
    projection = llm_navigation.build_projection(_map())

    assert projection["generated_from"] == ".repo-map.json"
    assert projection["modules"]["tools.alpha"]["exports"] == ["pick"]


def test_context_packet_keeps_direct_hits_and_adds_neighbors():
    packet = llm_navigation.build_context_packet(llm_navigation.build_projection(_map()), "alpha select", budget_chars=20)

    assert packet["direct_modules"] == ["tools.alpha"]
    assert packet["modules"][0]["module"] == "tools.alpha"
    assert packet["truncated"] is True
