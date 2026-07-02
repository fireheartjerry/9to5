"""Acceptance tests for the active alerting system (monitoring.alerter).

Validates:
  * checkAndNotify fires and deduplicates alerts
  * low success rate, high avg delay, max retries alerts all trigger
  * critical event late-detection triggers
  * in-window events do NOT produce alerts
  * dedup suppresses repeat notifications within TTL window
  * resetState / getNotifiedKeys helpers work
  * startAlertLoop / stopAlertLoop lifecycle is idempotent
  * Discord send is called when alerts fire (stubbed to avoid real REST)

Run: python C:/9to5/tests/test_active_alerting.py
     python -m pytest tests/test_active_alerting.py
"""
from __future__ import annotations

import sys
import time
import unittest
from pathlib import Path
from unittest import mock

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import monitoring
import monitoring.alerter as alerter
from monitoring.tracker import (
    CRITICAL_DETECTION_WINDOW_SECS,
    MAX_DELAY_SECONDS,
    MAX_RETRIES,
    SUCCESS_RATE_MIN,
)


def _reset_all():
    monitoring.reset()
    alerter.resetState()


class TestCheckAndNotifyBasic(unittest.TestCase):
    def setUp(self):
        _reset_all()

    def tearDown(self):
        _reset_all()

    def test_no_alerts_when_no_data(self):
        fired = alerter.checkAndNotify()
        self.assertEqual(fired, [])

    def test_no_alerts_when_within_thresholds(self):
        # 100% success, no delay, no retries
        for _ in range(5):
            monitoring.record_execution("w1", True, 1.0, retries=0)
        fired = alerter.checkAndNotify()
        self.assertEqual(fired, [])


class TestLowSuccessRateAlert(unittest.TestCase):
    def setUp(self):
        _reset_all()

    def tearDown(self):
        _reset_all()

    def test_fires_when_rate_below_threshold(self):
        # 0% success -> below 90%
        for _ in range(4):
            monitoring.record_execution("w1", False, 1.0)
        with mock.patch("monitoring.alerter._notifyAlert") as mock_notify:
            fired = alerter.checkAndNotify()
        self.assertTrue(any("low_success_rate" in k for k in fired))
        mock_notify.assert_called()

    def test_does_not_fire_when_above_threshold(self):
        # 100% success
        for _ in range(10):
            monitoring.record_execution("w1", True, 1.0)
        with mock.patch("monitoring.alerter._notifyAlert") as mock_notify:
            fired = alerter.checkAndNotify()
        self.assertFalse(any("low_success_rate" in k for k in fired))
        for call in mock_notify.call_args_list:
            self.assertNotEqual(call[0][0].get("type"), "low_success_rate")


class TestHighAvgDelayAlert(unittest.TestCase):
    def setUp(self):
        _reset_all()

    def tearDown(self):
        _reset_all()

    def test_fires_when_avg_delay_exceeds_threshold(self):
        monitoring.record_execution("w1", True, MAX_DELAY_SECONDS + 1.0)
        with mock.patch("monitoring.alerter._notifyAlert") as mock_notify:
            fired = alerter.checkAndNotify()
        self.assertTrue(any("high_avg_delay" in k for k in fired))
        mock_notify.assert_called()

    def test_does_not_fire_when_delay_within_threshold(self):
        monitoring.record_execution("w1", True, 1.0)
        with mock.patch("monitoring.alerter._notifyAlert"):
            fired = alerter.checkAndNotify()
        self.assertFalse(any("high_avg_delay" in k for k in fired))


class TestMaxRetriesAlert(unittest.TestCase):
    def setUp(self):
        _reset_all()

    def tearDown(self):
        _reset_all()

    def test_fires_when_retries_at_threshold(self):
        monitoring.record_execution("w-retry", True, 1.0, retries=MAX_RETRIES)
        with mock.patch("monitoring.alerter._notifyAlert") as mock_notify:
            fired = alerter.checkAndNotify()
        self.assertTrue(any("max_retries_exceeded" in k for k in fired))
        mock_notify.assert_called()

    def test_fires_when_retries_above_threshold(self):
        monitoring.record_execution("w-retry2", True, 1.0, retries=MAX_RETRIES + 2)
        with mock.patch("monitoring.alerter._notifyAlert"):
            fired = alerter.checkAndNotify()
        self.assertTrue(any("max_retries_exceeded:w-retry2" in k for k in fired))

    def test_does_not_fire_below_threshold(self):
        monitoring.record_execution("w-ok", True, 1.0, retries=MAX_RETRIES - 1)
        with mock.patch("monitoring.alerter._notifyAlert"):
            fired = alerter.checkAndNotify()
        self.assertFalse(any("max_retries_exceeded" in k for k in fired))


class TestCriticalEventAlert(unittest.TestCase):
    def setUp(self):
        _reset_all()

    def tearDown(self):
        _reset_all()

    def test_fires_for_late_detected_event(self):
        # occurred_at is far in the past -> lag > 120s
        old_ts = time.time() - (CRITICAL_DETECTION_WINDOW_SECS + 10.0)
        monitoring.record_critical_event("evt-1", "disk_full", occurred_at=old_ts)
        with mock.patch("monitoring.alerter._notifyCriticalEvent") as mock_notify:
            fired = alerter.checkAndNotify()
        self.assertTrue(any("critical_late:evt-1" in k for k in fired))
        mock_notify.assert_called()

    def test_does_not_fire_for_in_window_event(self):
        # occurred_at = now -> lag ~= 0, below threshold
        monitoring.record_critical_event("evt-2", "cpu_spike", occurred_at=time.time())
        with mock.patch("monitoring.alerter._notifyCriticalEvent") as mock_notify:
            fired = alerter.checkAndNotify()
        self.assertFalse(any("critical_late:evt-2" in k for k in fired))
        mock_notify.assert_not_called()


class TestDeduplification(unittest.TestCase):
    def setUp(self):
        _reset_all()

    def tearDown(self):
        _reset_all()

    def test_same_alert_not_fired_twice_in_ttl_window(self):
        for _ in range(4):
            monitoring.record_execution("w1", False, 1.0)
        with mock.patch("monitoring.alerter._notifyAlert") as mock_notify:
            fired1 = alerter.checkAndNotify()
            fired2 = alerter.checkAndNotify()
        # first call fires, second must not
        self.assertTrue(any("low_success_rate" in k for k in fired1))
        self.assertFalse(any("low_success_rate" in k for k in fired2))
        # _notifyAlert called exactly once
        low_rate_calls = [
            c for c in mock_notify.call_args_list
            if c[0][0].get("type") == "low_success_rate"
        ]
        self.assertEqual(len(low_rate_calls), 1)

    def test_alert_re_fires_after_ttl_expires(self):
        monitoring.record_execution("w1", False, 1.0)
        with mock.patch("monitoring.alerter._notifyAlert"):
            alerter.checkAndNotify()
        # Force TTL expiry by backdating the notified timestamp
        with alerter._lock:
            for key in list(alerter._notified):
                alerter._notified[key] -= (alerter.DEDUP_TTL_SECONDS + 1)
        with mock.patch("monitoring.alerter._notifyAlert") as mock_notify2:
            fired = alerter.checkAndNotify()
        self.assertTrue(len(fired) > 0)
        mock_notify2.assert_called()


class TestGetNotifiedKeys(unittest.TestCase):
    def setUp(self):
        _reset_all()

    def tearDown(self):
        _reset_all()

    def test_empty_initially(self):
        self.assertEqual(alerter.getNotifiedKeys(), {})

    def test_populated_after_fire(self):
        monitoring.record_execution("w1", False, 1.0)
        with mock.patch("monitoring.alerter._notifyAlert"):
            alerter.checkAndNotify()
        keys = alerter.getNotifiedKeys()
        self.assertIn("low_success_rate", keys)


class TestAlertEmbedStructure(unittest.TestCase):
    """Verify embed dicts have required Discord fields."""

    def test_low_success_rate_embed(self):
        embed = alerter._buildAlertEmbed(
            "low_success_rate",
            "rate 80% < 90% threshold",
            {"value": 0.8, "threshold": SUCCESS_RATE_MIN},
        )
        self._assertEmbed(embed)
        self.assertIn("Low Success Rate", embed["title"])

    def test_high_avg_delay_embed(self):
        embed = alerter._buildAlertEmbed(
            "high_avg_delay",
            "delay 400s > 300s",
            {"value": 400.0, "threshold": MAX_DELAY_SECONDS},
        )
        self._assertEmbed(embed)
        self.assertIn("High Average Delay", embed["title"])

    def test_max_retries_embed(self):
        embed = alerter._buildAlertEmbed(
            "max_retries_exceeded",
            "workflow hit 3 retries",
            {"workflow_id": "wf-x", "retries": MAX_RETRIES},
        )
        self._assertEmbed(embed)
        self.assertIn("Max Retries", embed["title"])

    def test_critical_late_embed(self):
        embed = alerter._buildAlertEmbed(
            "critical_event_late_detection",
            "event detected late",
            {"lag_seconds": 150.0},
        )
        self._assertEmbed(embed)
        self.assertIn("Critical Event", embed["title"])

    def _assertEmbed(self, embed: dict):
        self.assertIn("title", embed)
        self.assertIn("color", embed)
        self.assertIn("description", embed)
        self.assertIn("timestamp", embed)
        self.assertIsInstance(embed["fields"], list)
        self.assertTrue(len(embed["fields"]) > 0)


class TestAlertLoopLifecycle(unittest.TestCase):
    def setUp(self):
        _reset_all()

    def tearDown(self):
        _reset_all()

    def test_start_stop_idempotent(self):
        alerter.startAlertLoop(interval_seconds=0.05)
        time.sleep(0.02)
        thread1 = alerter._thread
        # Second start must be no-op
        alerter.startAlertLoop(interval_seconds=0.05)
        self.assertIs(alerter._thread, thread1)
        alerter.stopAlertLoop()
        time.sleep(0.15)
        self.assertFalse(thread1.is_alive())

    def test_loop_calls_check_and_notify(self):
        call_count = [0]
        orig = alerter.checkAndNotify

        def _counting():
            call_count[0] += 1
            return orig()

        with mock.patch.object(alerter, "checkAndNotify", side_effect=_counting):
            alerter.startAlertLoop(interval_seconds=0.05)
            time.sleep(0.2)
            alerter.stopAlertLoop()
            time.sleep(0.1)

        self.assertGreater(call_count[0], 1)


class TestMultipleAlertsSimultaneous(unittest.TestCase):
    def setUp(self):
        _reset_all()

    def tearDown(self):
        _reset_all()

    def test_all_threshold_types_can_fire_together(self):
        # Trigger low success rate + max retries in one batch
        monitoring.record_execution("w1", False, 1.0, retries=MAX_RETRIES)
        with mock.patch("monitoring.alerter._notifyAlert") as mock_notify:
            fired = alerter.checkAndNotify()
        types_fired = set(fired)
        self.assertIn("low_success_rate", types_fired)
        self.assertIn("max_retries_exceeded:w1", types_fired)
        self.assertGreaterEqual(mock_notify.call_count, 2)


if __name__ == "__main__":
    import tests.test_event_alerting as _evt_module
    _loader = unittest.TestLoader()
    _suite = unittest.TestSuite()
    _suite.addTests(_loader.loadTestsFromModule(sys.modules[__name__]))
    _suite.addTests(_loader.loadTestsFromModule(_evt_module))
    _result = unittest.TextTestRunner(verbosity=2).run(_suite)
    sys.exit(0 if _result.wasSuccessful() else 1)
