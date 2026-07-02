"""Tests for trace-replay JSON output mode, ANSI color, timestamp/offset utilities, and integration."""
from __future__ import annotations

import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_spec = importlib.util.spec_from_file_location("trace_replay_cli", _ROOT / "agents" / "trace-replay.py")
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_replayEvents, _c = _mod._replayEvents, _mod._c

_T0 = "2026-01-01T00:00:00+00:00"
_T1 = "2026-01-01T00:00:01+00:00"
_T2 = "2026-01-01T00:00:02+00:00"
_T3 = "2026-01-01T00:00:03+00:00"

_MIXED: list[dict] = [
    {"ts": _T0, "run_id": "m", "subtask_id": "st-A", "event": "verification_failed"},
    {"ts": _T1, "run_id": "m", "subtask_id": "st-A", "event": "replan_triggered"},
    {"ts": _T2, "run_id": "m", "subtask_id": "st-B", "event": "adversary_challenged"},
    {"ts": _T3, "run_id": "m", "subtask_id": "st-B", "event": "executor_failed"},
    {"ts": _T0, "run_id": "m", "subtask_id": "st-C", "event": "run_completed"},
    {"ts": _T1, "run_id": "m", "subtask_id": "st-C", "event": "verify_passed"},
    {"ts": _T2, "run_id": "m", "subtask_id": "st-C", "event": "verify_passed"},
]
_CLEAN: list[dict] = [
    {"ts": _T0, "run_id": "c", "subtask_id": "st-X", "event": "run_completed"},
    {"ts": _T1, "run_id": "c", "subtask_id": "st-X", "event": "verify_passed"},
]


def _capture_replay(events, threshold, run_id="t", **kw) -> tuple[int, str]:
    """Run _replayEvents capturing stdout; returns (divergence_count, captured_text)."""
    buf = io.StringIO()
    old, sys.stdout = sys.stdout, buf
    try:
        count = _replayEvents(events, threshold, run_id=run_id, **kw)
    finally:
        sys.stdout = old
    return count, buf.getvalue()


class TestJsonOutputMode(unittest.TestCase):

    def _json(self, events, threshold=10, run_id="j", **kw) -> dict:
        count, text = _capture_replay(events, threshold, run_id=run_id,
                                      output_format="json", **kw)
        return count, json.loads(text)

    def test_returns_correct_divergence_count(self):
        count, report = self._json(_MIXED, threshold=5, run_id="m")
        self.assertEqual(count, 4)
        self.assertEqual(report["divergence_count"], 4)

    def test_clean_trace_zero_divergences(self):
        count, report = self._json(_CLEAN, threshold=5, run_id="c")
        self.assertEqual(count, 0)
        self.assertEqual(report["divergence_count"], 0)

    def test_run_id_in_report(self):
        _, report = self._json(_CLEAN, run_id="my-run")
        self.assertEqual(report["run_id"], "my-run")

    def test_total_events_correct(self):
        _, report = self._json(_MIXED, threshold=5)
        self.assertEqual(report["total_events"], len(_MIXED))

    def test_report_has_required_keys(self):
        _, report = self._json(_CLEAN)
        for key in ("run_id", "total_events", "divergence_count",
                    "high_activity_count", "parallel_moments",
                    "divergences", "high_activity_subtasks"):
            with self.subTest(key=key):
                self.assertIn(key, report)

    def test_divergences_list_contains_dicts(self):
        _, report = self._json(_MIXED, threshold=5)
        self.assertIsInstance(report["divergences"], list)
        self.assertEqual(len(report["divergences"]), 4)
        for d in report["divergences"]:
            with self.subTest(d=d):
                self.assertIn("event", d)
                self.assertIn("kind", d)
                self.assertIn("subtask", d)

    def test_divergence_kinds_correct(self):
        _, report = self._json(_MIXED, threshold=5)
        kinds = {d["kind"] for d in report["divergences"]}
        self.assertEqual(kinds, {"FAIL", "REPLAN", "CHALLENGE"})

    def test_high_activity_subtasks_is_dict(self):
        events = [{"ts": _T0, "run_id": "h", "subtask_id": "busy", "event": "verify_passed"}] * 5
        _, report = self._json(events, threshold=3, run_id="h")
        self.assertIsInstance(report["high_activity_subtasks"], dict)
        self.assertIn("busy", report["high_activity_subtasks"])

    def test_high_activity_count_matches_subtasks_dict(self):
        events = [{"ts": _T0, "run_id": "h", "subtask_id": "busy", "event": "verify_passed"}] * 5
        _, report = self._json(events, threshold=3, run_id="h")
        self.assertEqual(report["high_activity_count"], len(report["high_activity_subtasks"]))

    def test_clean_subtask_not_in_high_activity(self):
        events = [{"ts": _T0, "run_id": "h", "subtask_id": "quiet", "event": "verify_passed"}] * 2
        _, report = self._json(events, threshold=5, run_id="h")
        self.assertNotIn("quiet", report["high_activity_subtasks"])

    def test_empty_events_produces_valid_json(self):
        count, report = self._json([], threshold=5, run_id="empty")
        self.assertEqual(count, 0)
        self.assertEqual(report["total_events"], 0)
        self.assertEqual(report["divergence_count"], 0)

    def test_parallel_moments_counted_in_json(self):
        events = [
            {"ts": _T0, "run_id": "p", "subtask_id": "st-P1", "event": "run_completed"},
            {"ts": _T0, "run_id": "p", "subtask_id": "st-P2", "event": "verify_passed"},
            {"ts": _T1, "run_id": "p", "subtask_id": "st-P1", "event": "verify_passed"},
        ]
        _, report = self._json(events, threshold=5, run_id="p")
        self.assertEqual(report["parallel_moments"], 1)

    def test_no_ansi_in_json_output(self):
        _, text = _capture_replay(_MIXED, threshold=5, output_format="json")
        self.assertNotIn("\033[", text)

    def test_offset_field_format(self):
        _, report = self._json(_MIXED, threshold=5)
        for d in report["divergences"]:
            self.assertTrue(d["offset"].startswith("T+"), d["offset"])

    def test_ts_field_is_numeric(self):
        _, report = self._json(_MIXED, threshold=5)
        for d in report["divergences"]:
            self.assertIsInstance(d["ts"], float)


class TestColorHelper(unittest.TestCase):

    def setUp(self):
        self._saved = _mod._USE_COLOR

    def tearDown(self):
        _mod._USE_COLOR = self._saved

    def test_color_off_returns_plain_text(self):
        _mod._USE_COLOR = False
        self.assertEqual(_c("FAIL", "hello"), "hello")

    def test_color_on_wraps_with_ansi(self):
        _mod._USE_COLOR = True
        result = _c("FAIL", "hello")
        self.assertIn("\033[", result)
        self.assertIn("hello", result)

    def test_color_off_unknown_kind_returns_plain(self):
        _mod._USE_COLOR = False
        self.assertEqual(_c("UNKNOWN_KIND", "text"), "text")

    def test_color_on_unknown_kind_returns_text_with_reset(self):
        _mod._USE_COLOR = True
        result = _c("UNKNOWN_KIND", "text")
        self.assertIn("text", result)

    def test_all_known_kinds_have_codes(self):
        _mod._USE_COLOR = True
        for kind in ("FAIL", "REPLAN", "CHALLENGE", "PASS", "INFO", "HIGH", "HEADER"):
            with self.subTest(kind=kind):
                result = _c(kind, "x")
                self.assertIn("\033[", result)


class TestParseTs(unittest.TestCase):

    def test_iso_with_offset_parses(self):
        ts = _mod._parseTs("2026-01-01T00:00:00+00:00")
        self.assertIsNotNone(ts)
        self.assertIsInstance(ts, float)

    def test_z_suffix_parses(self):
        ts = _mod._parseTs("2026-01-01T00:00:00Z")
        self.assertIsNotNone(ts)

    def test_none_returns_none(self):
        self.assertIsNone(_mod._parseTs(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(_mod._parseTs(""))

    def test_invalid_string_returns_none(self):
        self.assertIsNone(_mod._parseTs("not-a-timestamp"))
        self.assertIsNone(_mod._parseTs("2026-13-45T99:99:99+00:00"))

    def test_ordering_preserved(self):
        t0 = _mod._parseTs("2026-01-01T00:00:00+00:00")
        t1 = _mod._parseTs("2026-01-01T00:00:01+00:00")
        self.assertLess(t0, t1)

    def test_one_second_apart(self):
        t0 = _mod._parseTs("2026-01-01T00:00:00+00:00")
        t1 = _mod._parseTs("2026-01-01T00:00:01+00:00")
        self.assertAlmostEqual(t1 - t0, 1.0, places=5)


class TestFmtOffset(unittest.TestCase):

    def test_zero_offset(self):
        self.assertEqual(_mod._fmtOffset(100.0, 100.0), "T+0.00s")

    def test_positive_offset(self):
        self.assertEqual(_mod._fmtOffset(100.0, 101.5), "T+1.50s")

    def test_two_decimal_places(self):
        result = _mod._fmtOffset(0.0, 3.14159)
        self.assertTrue(result.startswith("T+3.14s"), result)

    def test_large_offset(self):
        result = _mod._fmtOffset(0.0, 3600.0)
        self.assertIn("3600.00", result)


class TestJsonWithParallelEvents(unittest.TestCase):

    def test_parallel_moments_reported_in_json(self):
        events = [
            {"ts": _T0, "run_id": "p", "subtask_id": "st-1", "event": "run_completed"},
            {"ts": _T0, "run_id": "p", "subtask_id": "st-2", "event": "run_completed"},
            {"ts": _T1, "run_id": "p", "subtask_id": "st-1", "event": "verify_passed"},
            {"ts": _T1, "run_id": "p", "subtask_id": "st-2", "event": "verify_passed"},
        ]
        count, text = _capture_replay(events, threshold=5, run_id="p", output_format="json")
        report = json.loads(text)
        self.assertEqual(report["parallel_moments"], 2)
        self.assertEqual(count, 0)

    def test_divergence_in_parallel_trace(self):
        events = [
            {"ts": _T0, "run_id": "p", "subtask_id": "st-1", "event": "verification_failed"},
            {"ts": _T0, "run_id": "p", "subtask_id": "st-2", "event": "run_completed"},
        ]
        count, text = _capture_replay(events, threshold=5, run_id="p", output_format="json")
        report = json.loads(text)
        self.assertEqual(count, 1)
        self.assertEqual(report["divergence_count"], 1)
        self.assertEqual(report["parallel_moments"], 1)
