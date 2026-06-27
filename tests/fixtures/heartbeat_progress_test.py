"""Explicit-only heartbeat smoke test for `python tools/dev.py heartbeat-test`."""
from __future__ import annotations

import time


def test_heartbeat_progress_fixture():
    time.sleep(2.2)
    assert True
