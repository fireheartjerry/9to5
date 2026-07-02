r"""Tests for monitoring.tracker -- success-rate / delay / alert logic.

Acceptance criteria verified:
  * success rate >= 90% threshold alert fires below 90%
  * avg delay > 300s threshold alert fires above 300s
  * max-retries alert fires at >= MAX_RETRIES (3)
  * get_success_rate / get_avg_delay return None with no data
  * per-workflow filtering works
  * reset() fully clears state

Run: python -m pytest tests/test_monitoring.py
     python C:\9to5\tests\test_monitoring.py
"""
import sys
import time
import unittest
from pathlib import Path
from unittest import mock

# Ensure repo root is importable whether invoked via pytest or directly.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import config
import monitoring
import monitoring.alerter as alerter
from monitoring.tracker import (
    CRITICAL_DETECTION_WINDOW_SECS,
    MAX_DELAY_SECONDS,
    MAX_RETRIES,
    SUCCESS_RATE_MIN,
)

_SAVED_DISCORD: dict = {}


def setUpModule():
    """Sandbox Discord so no notify path can fire a live REST call, even under bare
    ``python tests/test_monitoring.py`` (which bypasses the pytest-only fixture)."""
    _SAVED_DISCORD["token"] = config.DISCORD_BOT_TOKEN
    _SAVED_DISCORD["channel"] = config.DISCORD_CHANNEL_ID
    config.DISCORD_BOT_TOKEN = ""
    config.DISCORD_CHANNEL_ID = 0


def tearDownModule():
    config.DISCORD_BOT_TOKEN = _SAVED_DISCORD.get("token", config.DISCORD_BOT_TOKEN)
    config.DISCORD_CHANNEL_ID = _SAVED_DISCORD.get("channel", config.DISCORD_CHANNEL_ID)


class TestSuccessRate(unittest.TestCase):
    def setUp(self):
        monitoring.reset()

    def test_no_data_returns_none(self):
        self.assertIsNone(monitoring.get_success_rate())

    def test_all_success(self):
        for _ in range(5):
            monitoring.record_execution("w1", True, 10.0)
        self.assertAlmostEqual(monitoring.get_success_rate(), 1.0)

    def test_all_failure(self):
        for _ in range(4):
            monitoring.record_execution("w1", False, 10.0)
        self.assertAlmostEqual(monitoring.get_success_rate(), 0.0)

    def test_partial_rate(self):
        monitoring.record_execution("w1", True, 10.0)
        monitoring.record_execution("w1", False, 10.0)
        self.assertAlmostEqual(monitoring.get_success_rate(), 0.5)

    def test_per_workflow_filter(self):
        monitoring.record_execution("w1", True, 10.0)
        monitoring.record_execution("w2", False, 10.0)
        self.assertAlmostEqual(monitoring.get_success_rate("w1"), 1.0)
        self.assertAlmostEqual(monitoring.get_success_rate("w2"), 0.0)

    def test_unknown_workflow_none(self):
        monitoring.record_execution("w1", True, 10.0)
        self.assertIsNone(monitoring.get_success_rate("unknown"))


class TestAvgDelay(unittest.TestCase):
    def setUp(self):
        monitoring.reset()

    def test_no_data_returns_none(self):
        self.assertIsNone(monitoring.get_avg_delay())

    def test_avg_computed(self):
        monitoring.record_execution("w1", True, 100.0)
        monitoring.record_execution("w1", True, 200.0)
        self.assertAlmostEqual(monitoring.get_avg_delay(), 150.0)

    def test_per_workflow_delay(self):
        monitoring.record_execution("w1", True, 60.0)
        monitoring.record_execution("w2", True, 240.0)
        self.assertAlmostEqual(monitoring.get_avg_delay("w1"), 60.0)
        self.assertAlmostEqual(monitoring.get_avg_delay("w2"), 240.0)


class TestAlerts(unittest.TestCase):
    def setUp(self):
        monitoring.reset()

    def test_no_alerts_on_healthy_data(self):
        for _ in range(10):
            monitoring.record_execution("w1", True, 30.0)
        self.assertEqual(monitoring.get_alerts(), [])

    def test_low_success_rate_alert(self):
        # 80% success -- below 90% threshold
        for _ in range(8):
            monitoring.record_execution("w1", True, 10.0)
        for _ in range(2):
            monitoring.record_execution("w1", False, 10.0)
        alerts = monitoring.get_alerts()
        types = [a["type"] for a in alerts]
        self.assertIn("low_success_rate", types)
        alert = next(a for a in alerts if a["type"] == "low_success_rate")
        self.assertAlmostEqual(alert["value"], 0.8)
        self.assertEqual(alert["threshold"], SUCCESS_RATE_MIN)

    def test_no_alert_at_exactly_threshold(self):
        # exactly 90% -- should NOT alert
        for _ in range(9):
            monitoring.record_execution("w1", True, 10.0)
        monitoring.record_execution("w1", False, 10.0)
        types = [a["type"] for a in monitoring.get_alerts()]
        self.assertNotIn("low_success_rate", types)

    def test_high_delay_alert(self):
        monitoring.record_execution("w1", True, MAX_DELAY_SECONDS + 1.0)
        alerts = monitoring.get_alerts()
        types = [a["type"] for a in alerts]
        self.assertIn("high_avg_delay", types)
        alert = next(a for a in alerts if a["type"] == "high_avg_delay")
        self.assertGreater(alert["value"], MAX_DELAY_SECONDS)

    def test_no_delay_alert_under_threshold(self):
        monitoring.record_execution("w1", True, MAX_DELAY_SECONDS - 1.0)
        types = [a["type"] for a in monitoring.get_alerts()]
        self.assertNotIn("high_avg_delay", types)

    def test_max_retries_alert(self):
        monitoring.record_execution("w1", False, 10.0, retries=MAX_RETRIES)
        alerts = monitoring.get_alerts()
        types = [a["type"] for a in alerts]
        self.assertIn("max_retries_exceeded", types)
        alert = next(a for a in alerts if a["type"] == "max_retries_exceeded")
        self.assertEqual(alert["workflow_id"], "w1")
        self.assertEqual(alert["retries"], MAX_RETRIES)

    def test_no_retry_alert_below_threshold(self):
        monitoring.record_execution("w1", False, 10.0, retries=MAX_RETRIES - 1)
        types = [a["type"] for a in monitoring.get_alerts()]
        self.assertNotIn("max_retries_exceeded", types)

    def test_multiple_alerts_fire_together(self):
        # Low rate + high delay
        monitoring.record_execution("w1", False, MAX_DELAY_SECONDS + 10.0)
        monitoring.record_execution("w1", False, MAX_DELAY_SECONDS + 10.0)
        types = {a["type"] for a in monitoring.get_alerts()}
        self.assertIn("low_success_rate", types)
        self.assertIn("high_avg_delay", types)

    def test_alerts_message_is_string(self):
        monitoring.record_execution("w1", False, 10.0, retries=MAX_RETRIES)
        for alert in monitoring.get_alerts():
            self.assertIsInstance(alert.get("message"), str)
            self.assertGreater(len(alert["message"]), 0)


class TestReset(unittest.TestCase):
    def test_reset_clears_records_and_alerts(self):
        monitoring.record_execution("w1", False, MAX_DELAY_SECONDS + 100.0)
        self.assertIsNotNone(monitoring.get_success_rate())
        self.assertTrue(len(monitoring.get_alerts()) > 0)
        monitoring.reset()
        self.assertIsNone(monitoring.get_success_rate())
        self.assertIsNone(monitoring.get_avg_delay())
        self.assertEqual(monitoring.get_alerts(), [])


class TestGetAlertsSnapshot(unittest.TestCase):
    """get_alerts() must return a copy, not the internal list."""
    def setUp(self):
        monitoring.reset()

    def test_mutation_does_not_affect_internal_state(self):
        monitoring.record_execution("w1", False, 10.0)
        alerts = monitoring.get_alerts()
        alerts.append({"type": "fake"})
        self.assertNotEqual(monitoring.get_alerts(), alerts)


class TestCriticalDetectionWindow(unittest.TestCase):
    """B45: the detection window constant is 120s (2 minutes), matching every doc/spec."""

    def test_window_is_120_seconds(self):
        self.assertEqual(CRITICAL_DETECTION_WINDOW_SECS, 120.0)


class TestCriticalAlertSurvivesRefresh(unittest.TestCase):
    """B44: a late-detection critical alert must not be wiped by a later execution refresh."""

    def setUp(self):
        monitoring.reset()

    def tearDown(self):
        monitoring.reset()

    def _lateCritical(self):
        old_ts = time.time() - (CRITICAL_DETECTION_WINDOW_SECS + 30.0)
        monitoring.record_critical_event("evt-late", "system_failure", occurred_at=old_ts)

    def test_late_critical_alert_present_after_record(self):
        self._lateCritical()
        types = [a["type"] for a in monitoring.get_alerts()]
        self.assertIn("critical_event_late_detection", types)

    def test_late_critical_alert_survives_normal_execution(self):
        self._lateCritical()
        # A subsequent healthy execution triggers _refreshAlerts(); the critical alert
        # must survive because it is NOT derivable from execution records.
        monitoring.record_execution("w1", True, 10.0)
        alerts = monitoring.get_alerts()
        crit = [a for a in alerts if a["type"] == "critical_event_late_detection"]
        self.assertEqual(len(crit), 1)
        self.assertEqual(crit[0]["event_id"], "evt-late")

    def test_in_window_critical_adds_no_alert(self):
        monitoring.record_critical_event("evt-now", "system_failure", occurred_at=time.time())
        types = [a["type"] for a in monitoring.get_alerts()]
        self.assertNotIn("critical_event_late_detection", types)


class TestLateCriticalSingleAlert(unittest.TestCase):
    """B46: a single late-detected critical event must fire exactly one Discord notification."""

    def setUp(self):
        monitoring.reset()
        alerter.resetState()

    def tearDown(self):
        monitoring.reset()
        alerter.resetState()

    def test_single_notification_per_late_event(self):
        old_ts = time.time() - (CRITICAL_DETECTION_WINDOW_SECS + 30.0)
        monitoring.record_critical_event("evt-dup", "oom_kill", occurred_at=old_ts)
        with mock.patch("monitoring.alerter._notifyAlert") as mock_alert, \
                mock.patch("monitoring.alerter._notifyCriticalEvent") as mock_crit:
            fired = alerter.checkAndNotify()
        # Exactly one notification total for this event, under one dedup key.
        self.assertEqual(mock_crit.call_count, 1)
        crit_keys = [k for k in fired if "evt-dup" in k]
        self.assertEqual(len(crit_keys), 1)
        # The generic alert path must not also fire for the same critical event.
        for c in mock_alert.call_args_list:
            self.assertNotEqual(c[0][0].get("type"), "critical_event_late_detection")


if __name__ == "__main__":
    unittest.main()
