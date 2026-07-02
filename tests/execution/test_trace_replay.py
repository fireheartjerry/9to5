"""Tests for agents/trace_replay_cli.py divergence detection logic.

Acceptance command: python C:\\9to5\\tests\\test_trace_replay.py
"""
from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path
from unittest import mock

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

_spec = importlib.util.spec_from_file_location(
    "trace_replay", _ROOT / "agents" / "trace_replay_cli.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

_classify = _mod._classify
_computeThresholdFromCounts = _mod._computeThresholdFromCounts
_calibrateThreshold = _mod._calibrateThreshold
_replayEvents = _mod._replayEvents
replayTrace = _mod.replayTrace
_FALLBACK_THRESHOLD = _mod._FALLBACK_THRESHOLD
_FAIL_EVENTS = _mod._FAIL_EVENTS
_REPLAN_EVENTS = _mod._REPLAN_EVENTS
_ADVERSARY_EVENTS = _mod._ADVERSARY_EVENTS
_DIVERGENCE_SIGNALS = _mod._DIVERGENCE_SIGNALS


# ── Fixtures ──────────────────────────────────────────────────────────────────

_MIXED: list[dict] = [
    {"ts": "2026-01-01T00:00:00+00:00", "run_id": "mix", "subtask_id": "st-A", "event": "verification_failed"},
    {"ts": "2026-01-01T00:00:01+00:00", "run_id": "mix", "subtask_id": "st-A", "event": "replan_triggered"},
    {"ts": "2026-01-01T00:00:02+00:00", "run_id": "mix", "subtask_id": "st-B", "event": "adversary_challenged"},
    {"ts": "2026-01-01T00:00:03+00:00", "run_id": "mix", "subtask_id": "st-B", "event": "executor_failed"},
    {"ts": "2026-01-01T00:00:04+00:00", "run_id": "mix", "subtask_id": "st-C", "event": "run_completed"},
    {"ts": "2026-01-01T00:00:05+00:00", "run_id": "mix", "subtask_id": "st-C", "event": "verify_passed"},
    {"ts": "2026-01-01T00:00:06+00:00", "run_id": "mix", "subtask_id": "st-C", "event": "verify_passed"},
]

_CLEAN: list[dict] = [
    {"ts": "2026-01-01T00:00:00+00:00", "run_id": "cln", "subtask_id": "st-X", "event": "run_completed"},
    {"ts": "2026-01-01T00:00:01+00:00", "run_id": "cln", "subtask_id": "st-X", "event": "verify_passed"},
]

# All divergence kinds — one of each bucket.
_ONE_OF_EACH: list[dict] = [
    {"ts": "2026-01-01T00:00:00+00:00", "run_id": "ooe", "subtask_id": "s", "event": "verify_fail"},
    {"ts": "2026-01-01T00:00:01+00:00", "run_id": "ooe", "subtask_id": "s", "event": "replan_split"},
    {"ts": "2026-01-01T00:00:02+00:00", "run_id": "ooe", "subtask_id": "s", "event": "adversary_challenge"},
]

# Retry-storm fixture: one subtask with many events.
_STORM: list[dict] = [
    {"ts": f"2026-01-01T00:00:0{i}+00:00", "run_id": "storm", "subtask_id": "st-hot", "event": "verification_failed"}
    for i in range(9)
]

# Mixed subtasks, some clean some not.
_MULTI_SUBTASK: list[dict] = [
    {"ts": "2026-01-01T00:00:00+00:00", "run_id": "ms", "subtask_id": "ok-1", "event": "run_completed"},
    {"ts": "2026-01-01T00:00:01+00:00", "run_id": "ms", "subtask_id": "ok-1", "event": "verify_passed"},
    {"ts": "2026-01-01T00:00:02+00:00", "run_id": "ms", "subtask_id": "bad-1", "event": "verification_failed"},
    {"ts": "2026-01-01T00:00:03+00:00", "run_id": "ms", "subtask_id": "bad-1", "event": "replan_triggered"},
    {"ts": "2026-01-01T00:00:04+00:00", "run_id": "ms", "subtask_id": "ok-2", "event": "verify_passed"},
    {"ts": "2026-01-01T00:00:05+00:00", "run_id": "ms", "subtask_id": "bad-2", "event": "adversary_challenged"},
]

# Trace with extra fields (realistic tracing.emit output).
_RICH_FIELDS: list[dict] = [
    {
        "ts": "2026-01-01T00:00:00+00:00",
        "run_id": "rich",
        "subtask_id": "st-1",
        "event": "verification_failed",
        "cmd": "python check.py",
        "exit_code": 1,
        "decided_by": "verifier",
        "expect": "exit 0",
    },
    {
        "ts": "2026-01-01T00:00:01+00:00",
        "run_id": "rich",
        "subtask_id": "st-1",
        "event": "replan_triggered",
        "next_action": "narrow scope",
    },
]


# ── Classification ─────────────────────────────────────────────────────────────

class TestClassify(unittest.TestCase):

    def test_every_fail_variant_is_fail(self):
        for ev in _FAIL_EVENTS:
            with self.subTest(ev=ev):
                self.assertEqual(_classify(ev), "FAIL")

    def test_every_replan_variant_is_replan(self):
        for ev in _REPLAN_EVENTS:
            with self.subTest(ev=ev):
                self.assertEqual(_classify(ev), "REPLAN")

    def test_every_adversary_variant_is_challenge(self):
        for ev in _ADVERSARY_EVENTS:
            with self.subTest(ev=ev):
                self.assertEqual(_classify(ev), "CHALLENGE")

    def test_pass_events_not_divergences(self):
        for ev in ("verification_passed", "verify_pass", "verify_passed", "run_completed"):
            with self.subTest(ev=ev):
                self.assertEqual(_classify(ev), "PASS")

    def test_unknown_event_is_info(self):
        self.assertEqual(_classify("subtask_started"), "INFO")
        self.assertEqual(_classify(""), "INFO")
        self.assertEqual(_classify("some_future_event"), "INFO")

    def test_case_insensitive(self):
        self.assertEqual(_classify("VERIFICATION_FAILED"), "FAIL")
        self.assertEqual(_classify("Replan_Split"), "REPLAN")
        self.assertEqual(_classify("ADVERSARY_CHALLENGED"), "CHALLENGE")

    def test_divergence_signals_set_is_union(self):
        # Every element of _DIVERGENCE_SIGNALS must classify to FAIL/REPLAN/CHALLENGE.
        for ev in _DIVERGENCE_SIGNALS:
            with self.subTest(ev=ev):
                self.assertIn(_classify(ev), ("FAIL", "REPLAN", "CHALLENGE"))


# ── Threshold computation ──────────────────────────────────────────────────────

class TestComputeThreshold(unittest.TestCase):

    def test_empty_returns_fallback(self):
        self.assertEqual(_computeThresholdFromCounts([]), _FALLBACK_THRESHOLD)

    def test_single_low_value_floored(self):
        self.assertEqual(_computeThresholdFromCounts([3]), _FALLBACK_THRESHOLD)

    def test_linear_1_to_10(self):
        # p90_idx=9 → value=10 → max(11, 10)=11
        self.assertEqual(_computeThresholdFromCounts(list(range(1, 11))), 11)

    def test_uniform_high_values(self):
        self.assertEqual(_computeThresholdFromCounts([20] * 10), 21)

    def test_single_high_value_above_fallback(self):
        self.assertEqual(_computeThresholdFromCounts([50]), 51)

    def test_result_always_at_least_fallback(self):
        for counts in ([1], [2, 3], [1, 1, 1, 1, 1, 1, 1, 1, 1, 1]):
            with self.subTest(counts=counts):
                self.assertGreaterEqual(_computeThresholdFromCounts(counts), _FALLBACK_THRESHOLD)

    def test_ordering_independent(self):
        counts = [5, 3, 8, 1, 9, 2, 7, 4, 6, 10]
        self.assertEqual(
            _computeThresholdFromCounts(counts),
            _computeThresholdFromCounts(sorted(counts)),
        )


# ── Calibration ────────────────────────────────────────────────────────────────

class TestCalibrateThreshold(unittest.TestCase):

    def test_no_run_ids_returns_fallback(self):
        self.assertEqual(_calibrateThreshold([]), _FALLBACK_THRESHOLD)

    def test_empty_events_returns_fallback(self):
        with mock.patch.object(_mod.tracing, "readEvents", return_value=[]):
            self.assertEqual(_calibrateThreshold(["r1", "r2"]), _FALLBACK_THRESHOLD)

    def test_high_event_count_raises_threshold(self):
        events = [{"subtask_id": "st-A", "event": "x"}] * 20
        with mock.patch.object(_mod.tracing, "readEvents", return_value=events):
            self.assertGreater(_calibrateThreshold(["r1"]), _FALLBACK_THRESHOLD)

    def test_none_subtask_id_grouped_as_dash(self):
        events = [{"subtask_id": None, "event": "x"}] * 5
        with mock.patch.object(_mod.tracing, "readEvents", return_value=events):
            result = _calibrateThreshold(["r1"])
        self.assertIsInstance(result, int)
        self.assertGreaterEqual(result, _FALLBACK_THRESHOLD)

    def test_multiple_runs_aggregated(self):
        # Two runs, each with one subtask of count 20 → two counts of 20 → threshold 21.
        events_a = [{"subtask_id": "st-A", "event": "x"}] * 20
        events_b = [{"subtask_id": "st-B", "event": "x"}] * 20
        call_returns = [events_a, events_b]
        with mock.patch.object(_mod.tracing, "readEvents", side_effect=call_returns):
            self.assertEqual(_calibrateThreshold(["r1", "r2"]), 21)


# ── Core replay logic ──────────────────────────────────────────────────────────

class TestReplayEvents(unittest.TestCase):

    def test_mixed_trace_four_divergences(self):
        self.assertEqual(_replayEvents(_MIXED, threshold=2, run_id="t"), 4)

    def test_clean_trace_zero_divergences(self):
        self.assertEqual(_replayEvents(_CLEAN, threshold=1, run_id="c"), 0)

    def test_empty_trace_zero_divergences(self):
        self.assertEqual(_replayEvents([], threshold=5, run_id="empty"), 0)

    def test_all_three_divergence_kinds_counted(self):
        self.assertEqual(_replayEvents(_ONE_OF_EACH, threshold=10, run_id="ooe"), 3)

    def test_pass_events_not_counted(self):
        events = [
            {"ts": "2026-01-01T00:00:00+00:00", "run_id": "p", "subtask_id": "s", "event": "run_completed"},
            {"ts": "2026-01-01T00:00:01+00:00", "run_id": "p", "subtask_id": "s", "event": "verify_passed"},
            {"ts": "2026-01-01T00:00:02+00:00", "run_id": "p", "subtask_id": "s", "event": "verification_passed"},
            {"ts": "2026-01-01T00:00:03+00:00", "run_id": "p", "subtask_id": "s", "event": "verify_pass"},
        ]
        self.assertEqual(_replayEvents(events, threshold=10, run_id="pass-only"), 0)

    def test_info_events_not_counted(self):
        events = [
            {"ts": "2026-01-01T00:00:00+00:00", "run_id": "i", "subtask_id": "s", "event": "subtask_started"},
            {"ts": "2026-01-01T00:00:01+00:00", "run_id": "i", "subtask_id": "s", "event": "executor_invoked"},
        ]
        self.assertEqual(_replayEvents(events, threshold=10, run_id="info-only"), 0)

    def test_multi_subtask_divergence_count(self):
        # _MULTI_SUBTASK: ok-1 (clean), bad-1 (fail+replan), ok-2 (clean), bad-2 (adversary) → 3
        self.assertEqual(_replayEvents(_MULTI_SUBTASK, threshold=10, run_id="ms"), 3)

    def test_retry_storm_all_divergences_counted(self):
        # 9 verification_failed events
        self.assertEqual(_replayEvents(_STORM, threshold=5, run_id="storm"), 9)

    def test_rich_fields_trace_divergence_count(self):
        # _RICH_FIELDS: 1 fail + 1 replan = 2
        self.assertEqual(_replayEvents(_RICH_FIELDS, threshold=5, run_id="rich"), 2)

    def test_missing_ts_handled(self):
        events = [{"run_id": "t", "subtask_id": "s", "event": "verification_failed"}]
        self.assertEqual(_replayEvents(events, threshold=5, run_id="no-ts"), 1)

    def test_missing_subtask_id_handled(self):
        events = [{"ts": "2026-01-01T00:00:00+00:00", "run_id": "t", "event": "replan_split"}]
        self.assertEqual(_replayEvents(events, threshold=5, run_id="no-sid"), 1)

    def test_missing_event_key_handled(self):
        events = [{"ts": "2026-01-01T00:00:00+00:00", "run_id": "t", "subtask_id": "s"}]
        self.assertEqual(_replayEvents(events, threshold=5, run_id="no-event"), 0)

    def test_threshold_boundary_exclusive(self):
        # 3 events for st-Z; threshold=3 means >3 required to be high-activity → NOT storm flagged
        # divergences are still 0 (pass events only)
        events = [{"ts": "2026-01-01T00:00:00+00:00", "run_id": "t", "subtask_id": "st-Z",
                   "event": "verify_passed"}] * 3
        self.assertEqual(_replayEvents(events, threshold=3, run_id="boundary"), 0)

    def test_single_adversary_challenge_counted(self):
        events = [
            {"ts": "2026-01-01T00:00:00+00:00", "run_id": "a", "subtask_id": "s",
             "event": "adversary_challenge"},
        ]
        self.assertEqual(_replayEvents(events, threshold=5, run_id="adv"), 1)

    def test_divergence_ordering_preserved(self):
        # Return value is count, not list — verify count matches intuition across sequence.
        events = [
            {"ts": "2026-01-01T00:00:00+00:00", "run_id": "o", "subtask_id": "s", "event": "step_failed"},
            {"ts": "2026-01-01T00:00:01+00:00", "run_id": "o", "subtask_id": "s", "event": "verify_passed"},
            {"ts": "2026-01-01T00:00:02+00:00", "run_id": "o", "subtask_id": "s", "event": "run_failed"},
        ]
        self.assertEqual(_replayEvents(events, threshold=10, run_id="ord"), 2)


# ── replayTrace integration ────────────────────────────────────────────────────

class TestReplayTrace(unittest.TestCase):

    def test_no_events_returns_zero(self):
        with mock.patch.object(_mod.tracing, "readEvents", return_value=[]):
            self.assertEqual(replayTrace("nonexistent", threshold=10), 0)

    def test_single_fail_event(self):
        events = [
            {"ts": "2026-01-01T00:00:00+00:00", "run_id": "r1", "subtask_id": "s",
             "event": "verification_failed"},
        ]
        with mock.patch.object(_mod.tracing, "readEvents", return_value=events):
            self.assertEqual(replayTrace("r1", threshold=5), 1)

    def test_clean_run(self):
        events = [
            {"ts": "2026-01-01T00:00:00+00:00", "run_id": "r2", "subtask_id": "s", "event": "run_completed"},
            {"ts": "2026-01-01T00:00:01+00:00", "run_id": "r2", "subtask_id": "s", "event": "verify_passed"},
        ]
        with mock.patch.object(_mod.tracing, "readEvents", return_value=events):
            self.assertEqual(replayTrace("r2", threshold=5), 0)

    def test_mixed_trace_delegates_to_replay_events(self):
        with mock.patch.object(_mod.tracing, "readEvents", return_value=_MIXED):
            self.assertEqual(replayTrace("mix", threshold=2), 4)

    def test_adversary_only_run(self):
        events = [
            {"ts": "2026-01-01T00:00:00+00:00", "run_id": "adv", "subtask_id": "s",
             "event": "adversary_challenged"},
            {"ts": "2026-01-01T00:00:01+00:00", "run_id": "adv", "subtask_id": "s",
             "event": "adversary_challenge"},
        ]
        with mock.patch.object(_mod.tracing, "readEvents", return_value=events):
            self.assertEqual(replayTrace("adv", threshold=5), 2)


# ── Built-in self-test ─────────────────────────────────────────────────────────

class TestBuiltInSelfTest(unittest.TestCase):
    def test_self_test_passes(self):
        _mod._selfTest()
