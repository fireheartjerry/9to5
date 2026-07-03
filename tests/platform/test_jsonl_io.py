"""Tests for platform_core.core.jsonl_io."""
from __future__ import annotations

from platform_core.core import jsonl_io


def test_jsonl_reader_skips_torn_lines(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text('{"ok": 1}\n{bad\n{"ok": 2}\n', encoding="utf-8")

    records, skipped = jsonl_io.iterRecords(path)

    assert records == [{"ok": 1}, {"ok": 2}]
    assert skipped == 1
    assert jsonl_io.readTail(path, 2) == [{"ok": 2}]


def test_append_record_rotates_when_over_budget(tmp_path):
    path = tmp_path / "events.jsonl"
    path.write_text("x" * 10, encoding="utf-8")

    jsonl_io.appendRecord(path, {"new": True}, max_bytes=1)

    assert (tmp_path / "events.jsonl.1").exists()
    assert jsonl_io.iterRecords(path)[0] == [{"new": True}]
