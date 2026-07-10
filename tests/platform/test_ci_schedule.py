"""Tests for capacity-aware CI scheduling."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import ci_schedule  # noqa: E402


def test_lpt_balances_normal_lanes_deterministically():
    schedule = ci_schedule.plan_lanes([
        {"name": "a", "seconds": 9}, {"name": "b", "seconds": 8}, {"name": "c", "seconds": 1},
    ], workers=2)

    assert [[lane["name"] for lane in slot] for slot in schedule] == [["a"], ["b", "c"]]
    assert ci_schedule.makespan(schedule) == 9


def test_heavy_lane_uses_primary_slot():
    schedule = ci_schedule.plan_lanes([
        {"name": "fast", "seconds": 30, "heavy": True}, {"name": "smoke", "seconds": 5},
    ], workers=2)

    assert schedule[0][0]["name"] == "fast"
