"""Tests for platform_core/orchestration/human_nature_bridge/execution.py::biasEffortTiered.

biasEffortTiered is a BIDIRECTIONAL sibling of biasEffort: gated on config.HN_EXEC_AUTHORITY
AND an earned-authority tier of at least "soft", it may raise effort on "deliberate" routing
as well as lower it on "fast" routing. Below "soft" tier, or with the flag off, it is a
strict no-op passthrough -- mirrors the "cosmetic surface-only" contract from
docs/superpowers/specs/2026-07-06-human-nature-psyche-v2-design.md sec 4.1.
"""

from __future__ import annotations

import config

from platform_core.orchestration.human_nature_bridge.execution import biasEffortTiered


def test_tiered_deliberate_raises_one_tier_at_soft(monkeypatch):
    monkeypatch.setattr(config, "HN_EXEC_AUTHORITY", True)
    assert biasEffortTiered("default", "deliberate", "soft") == "high"


def test_tiered_fast_lowers_one_tier_at_soft(monkeypatch):
    monkeypatch.setattr(config, "HN_EXEC_AUTHORITY", True)
    assert biasEffortTiered("high", "fast", "soft") == "default"


def test_tiered_deliberate_clamps_at_top_tier(monkeypatch):
    monkeypatch.setattr(config, "HN_EXEC_AUTHORITY", True)
    assert biasEffortTiered("ultracode", "deliberate", "soft") == "ultracode"


def test_tiered_fast_clamps_at_bottom_tier(monkeypatch):
    monkeypatch.setattr(config, "HN_EXEC_AUTHORITY", True)
    assert biasEffortTiered("low", "fast", "soft") == "low"


def test_tiered_cosmetic_tier_unchanged_regardless_of_routing(monkeypatch):
    monkeypatch.setattr(config, "HN_EXEC_AUTHORITY", True)
    assert biasEffortTiered("default", "deliberate", "cosmetic") == "default"
    assert biasEffortTiered("default", "fast", "cosmetic") == "default"


def test_tiered_unknown_tier_unchanged_regardless_of_routing(monkeypatch):
    monkeypatch.setattr(config, "HN_EXEC_AUTHORITY", True)
    assert biasEffortTiered("default", "deliberate", "unknown") == "default"
    assert biasEffortTiered("default", "fast", "unknown") == "default"


def test_tiered_flag_off_unchanged_even_at_high_tier(monkeypatch):
    monkeypatch.setattr(config, "HN_EXEC_AUTHORITY", False)
    assert biasEffortTiered("default", "deliberate", "veto") == "default"
    assert biasEffortTiered("high", "fast", "veto") == "high"


def test_tiered_off_ladder_effort_unchanged(monkeypatch):
    monkeypatch.setattr(config, "HN_EXEC_AUTHORITY", True)
    assert biasEffortTiered("weird", "deliberate", "soft") == "weird"
    assert biasEffortTiered("weird", "fast", "soft") == "weird"


def test_tiered_higher_authority_tiers_also_authorized(monkeypatch):
    monkeypatch.setattr(config, "HN_EXEC_AUTHORITY", True)
    for tier in ("vote", "hold", "veto"):
        assert biasEffortTiered("default", "deliberate", tier) == "high"
        assert biasEffortTiered("high", "fast", tier) == "default"


def test_tiered_medium_alias_resolves_on_ladder(monkeypatch):
    monkeypatch.setattr(config, "HN_EXEC_AUTHORITY", True)
    # "medium" is a display alias of "default"; must ladder-resolve, not vanish.
    assert biasEffortTiered("medium", "deliberate", "soft") == "high"
