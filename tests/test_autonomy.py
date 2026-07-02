"""Tests for human_nature/autonomy.py — earned-autonomy dynamic trust contract.

RUN: python -m pytest tests/test_autonomy.py -v
"""
from __future__ import annotations

from human_nature.autonomy import cap_to, ceiling, revoke_on_miscalibration


# ---------------------------------------------------------------------------
# ceiling() — derives earned tier from track_record-shaped dict
# ---------------------------------------------------------------------------

class TestCeiling:
    def test_cold_start_total_zero_is_cosmetic(self):
        assert ceiling({"rate": 0.99, "total": 0}) == "cosmetic"

    def test_cold_start_total_four_is_cosmetic_regardless_of_rate(self):
        # total < 5 always cosmetic, even with perfect rate
        assert ceiling({"rate": 1.0, "total": 4}) == "cosmetic"

    def test_high_rate_high_volume_is_hard(self):
        assert ceiling({"rate": 0.85, "total": 20}) == "hard"

    def test_above_hard_threshold_is_hard(self):
        assert ceiling({"rate": 0.90, "total": 50}) == "hard"

    def test_mid_rate_is_soft(self):
        # rate >= 0.65 and total >= 5 but rate < 0.85 → soft
        assert ceiling({"rate": 0.65, "total": 10}) == "soft"
        assert ceiling({"rate": 0.75, "total": 10}) == "soft"

    def test_low_rate_is_cosmetic(self):
        # rate < 0.65 and total >= 5 → cosmetic
        assert ceiling({"rate": 0.50, "total": 10}) == "cosmetic"
        assert ceiling({"rate": 0.0, "total": 10}) == "cosmetic"

    def test_exact_thresholds(self):
        # exactly 0.65 → soft, exactly 0.85 with total 20 → hard
        assert ceiling({"rate": 0.65, "total": 5}) == "soft"
        assert ceiling({"rate": 0.85, "total": 20}) == "hard"
        # just below 0.85 → soft
        assert ceiling({"rate": 0.849, "total": 20}) == "soft"

    def test_hard_requires_total_ge_20(self):
        # rate >= 0.85 but total < 20 → soft
        assert ceiling({"rate": 0.90, "total": 19}) == "soft"


# ---------------------------------------------------------------------------
# revoke_on_miscalibration() — demote one level on recent underperformance
# ---------------------------------------------------------------------------

class TestRevokeOnMiscalibration:
    def test_hard_demotes_to_soft_on_low_rate(self):
        assert revoke_on_miscalibration("hard", recent_rate=0.3) == "soft"

    def test_soft_demotes_to_cosmetic_on_low_rate(self):
        assert revoke_on_miscalibration("soft", recent_rate=0.3) == "cosmetic"

    def test_cosmetic_floors_at_cosmetic(self):
        assert revoke_on_miscalibration("cosmetic", recent_rate=0.0) == "cosmetic"

    def test_no_demote_when_rate_above_threshold(self):
        assert revoke_on_miscalibration("hard", recent_rate=0.6) == "hard"
        assert revoke_on_miscalibration("soft", recent_rate=0.6) == "soft"

    def test_exactly_at_threshold_is_unchanged(self):
        # recent_rate == threshold → not below, no demote
        assert revoke_on_miscalibration("hard", recent_rate=0.5, threshold=0.5) == "hard"

    def test_custom_threshold(self):
        assert revoke_on_miscalibration("hard", recent_rate=0.7, threshold=0.8) == "soft"
        assert revoke_on_miscalibration("hard", recent_rate=0.9, threshold=0.8) == "hard"

    def test_demotes_exactly_one_level(self):
        # hard → soft (not cosmetic in one shot)
        result = revoke_on_miscalibration("hard", recent_rate=0.1)
        assert result == "soft"  # one level, not two


# ---------------------------------------------------------------------------
# cap_to() — opinion tier cannot exceed the earned autonomy ceiling
# ---------------------------------------------------------------------------

class TestCapTo:
    def test_hard_capped_to_soft_ceiling(self):
        assert cap_to("hard", "soft") == "soft"

    def test_hard_capped_to_cosmetic_ceiling(self):
        assert cap_to("hard", "cosmetic") == "cosmetic"

    def test_soft_capped_to_cosmetic_ceiling(self):
        assert cap_to("soft", "cosmetic") == "cosmetic"

    def test_tier_equal_to_ceiling_is_unchanged(self):
        assert cap_to("soft", "soft") == "soft"
        assert cap_to("hard", "hard") == "hard"
        assert cap_to("cosmetic", "cosmetic") == "cosmetic"

    def test_tier_below_ceiling_is_unchanged(self):
        assert cap_to("cosmetic", "soft") == "cosmetic"
        assert cap_to("soft", "hard") == "soft"
        assert cap_to("cosmetic", "hard") == "cosmetic"
