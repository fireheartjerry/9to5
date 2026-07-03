"""Tests for trace-replay parallel detection, bar chart rendering, and key-field extraction.

Covers:
  - Parallel subtask detection (_detectParallelSubtasks)
  - ASCII bar chart rendering (_renderBarChart)
  - Key-fields extraction (_keyFields)

Acceptance command: python -m pytest C:\\9to5\\tests\\test_trace_replay_parallel_render.py
"""
from __future__ import annotations

import importlib.util
import io
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_spec = importlib.util.spec_from_file_location(
    "trace_replay_cli", _ROOT / "agents" / "trace_replay_cli.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_detectParallelSubtasks = _mod._detectParallelSubtasks
_renderBarChart = _mod._renderBarChart
_keyFields = _mod._keyFields

_T0 = "2026-01-01T00:00:00+00:00"
_T1 = "2026-01-01T00:00:01+00:00"
_T2 = "2026-01-01T00:00:02+00:00"
_T3 = "2026-01-01T00:00:03+00:00"


# ── Parallel subtask detection ────────────────────────────────────────────────

class TestDetectParallelSubtasks(unittest.TestCase):

    def test_no_events_returns_empty(self):
        self.assertEqual(_detectParallelSubtasks([]), [])

    def test_single_event_no_parallel(self):
        events = [{"ts": _T0, "subtask_id": "st-A", "event": "run_completed"}]
        self.assertEqual(_detectParallelSubtasks(events), [])

    def test_same_subtask_same_ts_not_parallel(self):
        events = [
            {"ts": _T0, "subtask_id": "st-A", "event": "run_completed"},
            {"ts": _T0, "subtask_id": "st-A", "event": "verify_passed"},
        ]
        self.assertEqual(_detectParallelSubtasks(events), [])

    def test_two_subtasks_same_ts_detected(self):
        events = [
            {"ts": _T0, "subtask_id": "st-A", "event": "run_completed"},
            {"ts": _T0, "subtask_id": "st-B", "event": "run_completed"},
        ]
        result = _detectParallelSubtasks(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(set(result[0][1]), {"st-A", "st-B"})

    def test_three_subtasks_same_ts(self):
        events = [
            {"ts": _T0, "subtask_id": "st-A", "event": "run_completed"},
            {"ts": _T0, "subtask_id": "st-B", "event": "run_completed"},
            {"ts": _T0, "subtask_id": "st-C", "event": "run_completed"},
        ]
        result = _detectParallelSubtasks(events)
        self.assertEqual(len(result), 1)
        self.assertEqual(set(result[0][1]), {"st-A", "st-B", "st-C"})

    def test_two_parallel_moments(self):
        events = [
            {"ts": _T0, "subtask_id": "st-A", "event": "run_completed"},
            {"ts": _T0, "subtask_id": "st-B", "event": "run_completed"},
            {"ts": _T2, "subtask_id": "st-C", "event": "verify_passed"},
            {"ts": _T2, "subtask_id": "st-D", "event": "verify_passed"},
        ]
        result = _detectParallelSubtasks(events)
        self.assertEqual(len(result), 2)

    def test_sequential_subtasks_not_detected(self):
        events = [
            {"ts": _T0, "subtask_id": "st-A", "event": "run_completed"},
            {"ts": _T1, "subtask_id": "st-B", "event": "verify_passed"},
            {"ts": _T2, "subtask_id": "st-C", "event": "run_completed"},
        ]
        self.assertEqual(_detectParallelSubtasks(events), [])

    def test_missing_ts_events_skipped(self):
        events = [
            {"subtask_id": "st-A", "event": "run_completed"},   # no ts
            {"ts": _T0, "subtask_id": "st-B", "event": "run_completed"},
        ]
        self.assertEqual(_detectParallelSubtasks(events), [])

    def test_none_subtask_id_treated_as_dash(self):
        events = [
            {"ts": _T0, "subtask_id": None, "event": "run_completed"},
            {"ts": _T0, "subtask_id": "st-A", "event": "verify_passed"},
        ]
        result = _detectParallelSubtasks(events)
        self.assertEqual(len(result), 1)
        self.assertIn("-", result[0][1])
        self.assertIn("st-A", result[0][1])

    def test_result_sorted_by_timestamp(self):
        events = [
            {"ts": _T2, "subtask_id": "st-A", "event": "run_completed"},
            {"ts": _T2, "subtask_id": "st-B", "event": "run_completed"},
            {"ts": _T0, "subtask_id": "st-C", "event": "verify_passed"},
            {"ts": _T0, "subtask_id": "st-D", "event": "verify_passed"},
        ]
        result = _detectParallelSubtasks(events)
        self.assertEqual(len(result), 2)
        self.assertLessEqual(result[0][0], result[1][0])

    def test_subtask_ids_in_each_moment_sorted(self):
        events = [
            {"ts": _T0, "subtask_id": "zzz", "event": "run_completed"},
            {"ts": _T0, "subtask_id": "aaa", "event": "run_completed"},
        ]
        result = _detectParallelSubtasks(events)
        self.assertEqual(result[0][1], ["aaa", "zzz"])


# ── Bar chart rendering ───────────────────────────────────────────────────────

class TestRenderBarChart(unittest.TestCase):

    def _chart(self, counts: dict[str, int], threshold: int) -> str:
        buf = io.StringIO()
        old, sys.stdout = sys.stdout, buf
        try:
            _renderBarChart(counts, threshold)
        finally:
            sys.stdout = old
        return buf.getvalue()

    def test_empty_dict_produces_no_output(self):
        self.assertEqual(self._chart({}, threshold=5), "")

    def test_single_subtask_appears_in_chart(self):
        out = self._chart({"st-A": 5}, threshold=10)
        self.assertIn("st-A", out)

    def test_multiple_subtasks_all_appear(self):
        out = self._chart({"st-A": 3, "st-B": 7, "st-C": 1}, threshold=10)
        self.assertIn("st-A", out)
        self.assertIn("st-B", out)
        self.assertIn("st-C", out)

    def test_high_activity_flag_present_when_above_threshold(self):
        out = self._chart({"busy": 20}, threshold=10)
        self.assertIn("HIGH", out)

    def test_no_high_flag_below_threshold(self):
        old_color = _mod._USE_COLOR
        _mod._USE_COLOR = False
        try:
            out = self._chart({"quiet": 3}, threshold=10)
        finally:
            _mod._USE_COLOR = old_color
        self.assertNotIn("HIGH", out)

    def test_counts_appear_in_output(self):
        out = self._chart({"st-X": 42}, threshold=50)
        self.assertIn("42", out)

    def test_chart_header_present(self):
        out = self._chart({"st-A": 1}, threshold=5)
        self.assertIn("EVENT DISTRIBUTION", out)


# ── Key-fields extraction ─────────────────────────────────────────────────────

class TestKeyFields(unittest.TestCase):

    def test_empty_event_returns_empty_string(self):
        self.assertEqual(_keyFields({}), "")

    def test_standard_keys_excluded(self):
        ev = {"ts": "t", "run_id": "r", "subtask_id": "s", "event": "e", "cmd": "ls"}
        result = _keyFields(ev)
        self.assertNotIn("ts=", result)
        self.assertNotIn("run_id=", result)
        self.assertNotIn("subtask_id=", result)
        self.assertNotIn("event=", result)
        self.assertIn("cmd=", result)

    def test_none_values_excluded(self):
        ev = {"extra": None, "cmd": "ls"}
        result = _keyFields(ev)
        self.assertNotIn("extra=", result)
        self.assertIn("cmd=", result)

    def test_long_value_truncated(self):
        ev = {"detail": "x" * 200}
        result = _keyFields(ev)
        self.assertIn("...", result)
        self.assertLessEqual(len(result.split("=", 1)[1].strip("'")), 82)

    def test_at_most_six_fields_returned(self):
        ev = {f"k{i}": f"v{i}" for i in range(10)}
        result = _keyFields(ev)
        parts = [p for p in result.split("  ") if "=" in p]
        self.assertLessEqual(len(parts), 6)

    def test_multiple_extra_fields(self):
        ev = {"cmd": "python check.py", "exit_code": 1, "decided_by": "verifier"}
        result = _keyFields(ev)
        self.assertIn("cmd=", result)
        self.assertIn("exit_code=", result)
        self.assertIn("decided_by=", result)
