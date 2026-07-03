"""Tests for platform_core.core.clock."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from platform_core.core import clock


def test_parse_and_format_elapsed_are_tolerant():
    assert clock.parseIso("not a timestamp") is None
    assert clock.fmtElapsed(3) == "3s"
    assert clock.fmtElapsed(65) == "1m"
    assert clock.fmtElapsed(3665) == "1h 1m"


def test_run_clock_deadline_math():
    future = (datetime.now(timezone.utc) + timedelta(seconds=30)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(seconds=30)).isoformat()

    assert clock.RunClock(None).passed() is False
    assert clock.RunClock(future).remainingSeconds() > 0
    assert clock.RunClock(past).passed() is True
