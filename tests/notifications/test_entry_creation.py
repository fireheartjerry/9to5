"""Tests for makeEntry field-override protection."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from datetime import datetime, timezone

from notifications.entry import makeEntry, isValid


def test_at_not_overridden_by_extra():
    # 'at' is generated internally; a caller passing at= in extra must not clobber it.
    entry = makeEntry("subtask_done", "real detail", at="1970-01-01T00:00:00+00:00")
    assert entry["at"] != "1970-01-01T00:00:00+00:00"
    # validated kind/detail must be unaffected
    assert entry["kind"] == "subtask_done"
    assert entry["detail"] == "real detail"


def test_extra_kwargs_included_when_no_conflict():
    entry = makeEntry("replan", "replanned", subtask_id="st-001", attempt=2)
    assert entry["subtask_id"] == "st-001"
    assert entry["attempt"] == 2


def test_entry_is_valid():
    entry = makeEntry("complete", "task finished")
    assert isValid(entry)


def test_at_is_utc_iso():
    entry = makeEntry("aborted", "user aborted")
    dt = datetime.fromisoformat(entry["at"])
    assert dt.utcoffset() is not None


if __name__ == "__main__":
    test_at_not_overridden_by_extra()
    test_extra_kwargs_included_when_no_conflict()
    test_entry_is_valid()
    test_at_is_utc_iso()
    print("All tests passed.")
