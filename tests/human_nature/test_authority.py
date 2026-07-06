"""Tests for human_nature.authority — the 5-tier earned control authority ladder."""
from __future__ import annotations

import config
import pytest

from human_nature import authority


def test_tiers_ordering():
    assert authority.TIERS == ("cosmetic", "soft", "vote", "hold", "veto")


def test_band_low_is_cosmetic():
    assert authority.band(0.5) == "cosmetic"


def test_band_top_is_veto():
    assert authority.band(0.99) == "veto"


def test_band_thresholds():
    assert authority.band(config.HN_THETA_SOFT) == "soft"        # >= 0.60
    assert authority.band(config.HN_THETA_VOTE) == "vote"        # >= 0.72
    assert authority.band(config.HN_THETA_HOLD) == "hold"        # >= 0.85
    assert authority.band(config.HN_THETA_VETO) == "veto"        # >= 0.95
    assert authority.band(config.HN_THETA_SOFT - 0.001) == "cosmetic"


def test_earned_ceiling_cold_start_floor():
    # total < MIN_SAMPLES (5) → cosmetic even with a perfect rate.
    assert authority.earned_ceiling({"total": 2, "rate": 1.0}) == "cosmetic"


def test_earned_ceiling_top():
    # rate >= 0.95 and total >= 40 → veto (final resolve clamps this later).
    assert authority.earned_ceiling({"total": 50, "rate": 0.98}) in {"veto"}


def test_earned_ceiling_ladder():
    assert authority.earned_ceiling({"total": 10, "rate": 0.70}) == "soft"
    assert authority.earned_ceiling({"total": 20, "rate": 0.78}) == "vote"
    assert authority.earned_ceiling({"total": 20, "rate": 0.88}) == "hold"
    # High rate but too few samples cannot reach vote/hold/veto.
    assert authority.earned_ceiling({"total": 10, "rate": 0.99}) == "soft"


def test_cap_takes_min():
    assert authority.cap("veto", "soft") == "soft"
    assert authority.cap("soft", "veto") == "soft"
    assert authority.cap("hold", "hold") == "hold"


def test_resolve_clamps_to_authority_max():
    # Everything maxed but HN_AUTHORITY_MAX defaults "hold" → hold.
    got = authority.resolve(
        0.99, {"total": 50, "rate": 0.98}, "veto", "veto", "veto", "veto"
    )
    assert got == "hold"


def test_resolve_verifier_forces_cosmetic():
    got = authority.resolve(
        0.99, {"total": 50, "rate": 0.98}, "veto", "veto", "veto", "cosmetic"
    )
    assert got == "cosmetic"
