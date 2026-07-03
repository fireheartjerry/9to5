"""Tests for orchestration wall-clock formatting helpers."""
from __future__ import annotations

from datetime import datetime, timedelta

from platform_core.orchestration import time_utils


def test_fmt_elapsed_uses_compact_hms():
    assert time_utils._fmtElapsed(3661) == "1h01m01s"
    assert time_utils._fmtElapsed(61) == "0h01m01s"


def test_elapsed_since_unparseable_is_zero():
    assert time_utils._elapsedSince("nope") == 0.0
    past = (datetime.now() - timedelta(seconds=1)).isoformat()
    assert time_utils._elapsedSince(past) >= 0.0
