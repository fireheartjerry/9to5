"""Regression tests for platform_core/orchestration/subtask._subtaskNote.

The Obsidian note builder consumes a best-effort executor result dict whose
stdout/stderr may be non-strings (a malformed run, or the fuzz harness, yields
ints/lists/None). Building the note must never raise -- it previously crashed
with AttributeError: 'int' object has no attribute 'strip'.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from platform_core.orchestration import subtask as S


def _mk_subtask():
    return {"subtask_id": "st-001", "title": "demo", "status": "done"}


def test_asblock_coerces_non_strings():
    assert S._asBlock(None) == ""
    assert S._asBlock(5) == "5"
    assert S._asBlock([1, 2]) == "[1, 2]"
    assert S._asBlock("  hi  ") == "hi"


def test_note_survives_int_stdout():
    result = {"returncode": 0, "stdout": 5, "stderr": {"a": 1}, "is_error": "maybe"}
    note = S._subtaskNote(object(), _mk_subtask(), {"prompt": "p"}, result, None)
    assert "st-001" in note
    assert "5" in note  # the coerced stdout appears, no crash


def test_note_survives_non_string_verify_channels():
    vresult = {"passed": False, "cmd": "x", "expect": "exit_zero",
               "returncode": 1, "stdout": 42, "stderr": ["boom"]}
    result = {"returncode": 1, "stdout": None}
    note = S._subtaskNote(object(), _mk_subtask(), {"prompt": "p"}, result, vresult)
    assert "Verification" in note
    assert "42" in note and "boom" in note


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
