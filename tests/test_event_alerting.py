"""Acceptance tests: proactive alerting system for critical events.

Validates that the system detects and responds to critical events in real-time,
integrated with monitoring.tracker and monitoring.alerter.

Acceptance criteria verified:
  * Critical events detected within 2-minute window produce no alert
  * Critical events with lag > 2 minutes produce a proactive alert
  * Success-rate breach triggers alert within a single checkAndNotify call
  * High average delay triggers alert within a single checkAndNotify call
  * Max-retries exceeded triggers alert with correct workflow identifier
  * Deduplication suppresses repeated alerts within TTL window
  * Alert loop starts/stops cleanly; drives checkAndNotify on interval
  * All alert types carry required fields (type, message, threshold)

Run: python C:/9to5/tests/test_event_alerting.py
     python -m pytest tests/test_event_alerting.py
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
    """Sandbox Discord even under bare ``python tests/test_event_alerting.py`` (which bypasses
    the pytest-only ``_no_real_discord`` fixture). discord_bot._request short-circuits when token
    or channel is blank, so this guarantees no live REST call fires from any unmocked notify path."""
    _SAVED_DISCORD["token"] = config.DISCORD_BOT_TOKEN
    _SAVED_DISCORD["channel"] = config.DISCORD_CHANNEL_ID
    config.DISCORD_BOT_TOKEN = ""
    config.DISCORD_CHANNEL_ID = 0


def tearDownModule():
    config.DISCORD_BOT_TOKEN = _SAVED_DISCORD.get("token", config.DISCORD_BOT_TOKEN)
    config.DISCORD_CHANNEL_ID = _SAVED_DISCORD.get("channel", config.DISCORD_CHANNEL_ID)


def _reset():
    monitoring.reset()
    alerter.resetState()


class TestCriticalEventRealTimeDetection(unittest.TestCase):
    """Core requirement: events must be detected within CRITICAL_DETECTION_WINDOW_SECS."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_in_window_event_produces_no_alert(self):
        # Occurred just now -> lag ≈ 0, well within 2-minute window
        monitoring.record_critical_event("ev-now", "disk_io_spike", occurred_at=time.time())
        with mock.patch("monitoring.alerter._notifyCriticalEvent") as mock_notify:
            fired = alerter.checkAndNotify()
        late_keys = [k for k in fired if "critical_late" in k]
        self.assertEqual(late_keys, [], "in-window event must not fire a late-detection alert")
        mock_notify.assert_not_called()

    def test_late_event_produces_proactive_alert(self):
        # Occurred more than threshold ago -> must trigger proactive alert
        old_ts = time.time() - (CRITICAL_DETECTION_WINDOW_SECS + 30.0)
        monitoring.record_critical_event("ev-late", "oom_kill", occurred_at=old_ts)
        with mock.patch("monitoring.alerter._notifyCriticalEvent") as mock_notify:
            fired = alerter.checkAndNotify()
        self.assertTrue(
            any("critical_late:ev-late" in k for k in fired),
            "late event must produce a proactive alert",
        )
        mock_notify.assert_called_once()

    def test_detection_lag_stored_on_event(self):
        old_ts = time.time() - (CRITICAL_DETECTION_WINDOW_SECS + 60.0)
        monitoring.record_critical_event("ev-lag", "cpu_runaway", occurred_at=old_ts)
        events = monitoring.get_critical_events()
        self.assertEqual(len(events), 1)
        self.assertGreater(events[0]["lag_seconds"], CRITICAL_DETECTION_WINDOW_SECS)

    def test_multiple_late_events_each_fire(self):
        old_ts = time.time() - (CRITICAL_DETECTION_WINDOW_SECS + 10.0)
        monitoring.record_critical_event("ev-a", "type_x", occurred_at=old_ts)
        monitoring.record_critical_event("ev-b", "type_y", occurred_at=old_ts)
        # record_critical_event feeds the event into BOTH the critical-events list and the generic
        # _alerts list, so checkAndNotify drives _notifyAlert too -- mock it or it fires a real embed.
        with mock.patch("monitoring.alerter._notifyCriticalEvent") as mock_notify, \
                mock.patch("monitoring.alerter._notifyAlert"):
            fired = alerter.checkAndNotify()
        self.assertTrue(any("critical_late:ev-a" in k for k in fired))
        self.assertTrue(any("critical_late:ev-b" in k for k in fired))
        self.assertEqual(mock_notify.call_count, 2)


class TestThresholdAlerts(unittest.TestCase):
    """All configured thresholds trigger proactive Discord alerts."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_low_success_rate_triggers_alert(self):
        for _ in range(5):
            monitoring.record_execution("wf-rate", False, 10.0)
        with mock.patch("monitoring.alerter._notifyAlert") as mock_notify:
            fired = alerter.checkAndNotify()
        self.assertTrue(any("low_success_rate" in k for k in fired))
        mock_notify.assert_called()

    def test_healthy_success_rate_no_alert(self):
        for _ in range(10):
            monitoring.record_execution("wf-healthy", True, 10.0)
        with mock.patch("monitoring.alerter._notifyAlert") as mock_notify:
            fired = alerter.checkAndNotify()
        self.assertFalse(any("low_success_rate" in k for k in fired))

    def test_high_avg_delay_triggers_alert(self):
        monitoring.record_execution("wf-slow", True, MAX_DELAY_SECONDS + 60.0)
        with mock.patch("monitoring.alerter._notifyAlert") as mock_notify:
            fired = alerter.checkAndNotify()
        self.assertTrue(any("high_avg_delay" in k for k in fired))
        mock_notify.assert_called()

    def test_delay_within_threshold_no_alert(self):
        monitoring.record_execution("wf-fast", True, 10.0)
        with mock.patch("monitoring.alerter._notifyAlert") as mock_notify:
            fired = alerter.checkAndNotify()
        self.assertFalse(any("high_avg_delay" in k for k in fired))

    def test_max_retries_triggers_alert_with_workflow_id(self):
        monitoring.record_execution("wf-retry", True, 5.0, retries=MAX_RETRIES)
        with mock.patch("monitoring.alerter._notifyAlert") as mock_notify:
            fired = alerter.checkAndNotify()
        self.assertTrue(any("max_retries_exceeded:wf-retry" in k for k in fired))
        mock_notify.assert_called()

    def test_retries_below_threshold_no_alert(self):
        monitoring.record_execution("wf-ok", True, 5.0, retries=MAX_RETRIES - 1)
        with mock.patch("monitoring.alerter._notifyAlert") as mock_notify:
            fired = alerter.checkAndNotify()
        self.assertFalse(any("max_retries_exceeded" in k for k in fired))

    def test_all_threshold_types_can_fire_simultaneously(self):
        # One record that breaches success-rate, max-retries simultaneously
        monitoring.record_execution("wf-all", False, 1.0, retries=MAX_RETRIES)
        with mock.patch("monitoring.alerter._notifyAlert"):
            fired = alerter.checkAndNotify()
        fired_set = set(fired)
        self.assertIn("low_success_rate", fired_set)
        self.assertIn("max_retries_exceeded:wf-all", fired_set)


class TestAlertFieldIntegrity(unittest.TestCase):
    """Alerts must carry required fields for downstream consumers."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_alert_has_type_message_threshold(self):
        monitoring.record_execution("wf-x", False, MAX_DELAY_SECONDS + 1.0)
        alerts = monitoring.get_alerts()
        for alert in alerts:
            self.assertIn("type", alert)
            self.assertIsInstance(alert["type"], str)
            self.assertIn("message", alert)
            self.assertIsInstance(alert["message"], str)
            self.assertGreater(len(alert["message"]), 0)
            self.assertIn("threshold", alert)

    def test_critical_event_has_required_fields(self):
        old_ts = time.time() - (CRITICAL_DETECTION_WINDOW_SECS + 5.0)
        monitoring.record_critical_event("ev-fields", "net_drop", occurred_at=old_ts)
        events = monitoring.get_critical_events()
        self.assertEqual(len(events), 1)
        ev = events[0]
        for field in ("event_id", "event_type", "occurred_at", "detected_at", "lag_seconds"):
            self.assertIn(field, ev, f"missing field: {field}")


class TestDeduplication(unittest.TestCase):
    """Same alert must not fire twice within the TTL window."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_duplicate_suppressed_in_ttl_window(self):
        monitoring.record_execution("wf-dup", False, 1.0)
        with mock.patch("monitoring.alerter._notifyAlert") as mock_notify:
            fired1 = alerter.checkAndNotify()
            fired2 = alerter.checkAndNotify()
        self.assertTrue(any("low_success_rate" in k for k in fired1))
        self.assertFalse(any("low_success_rate" in k for k in fired2))
        calls = [c for c in mock_notify.call_args_list if c[0][0].get("type") == "low_success_rate"]
        self.assertEqual(len(calls), 1)

    def test_alert_refires_after_ttl_expiry(self):
        monitoring.record_execution("wf-refires", False, 1.0)
        with mock.patch("monitoring.alerter._notifyAlert"):
            alerter.checkAndNotify()
        # Backdate the notified timestamps to simulate TTL expiry
        with alerter._lock:
            for key in list(alerter._notified):
                alerter._notified[key] -= (alerter.DEDUP_TTL_SECONDS + 1)
        with mock.patch("monitoring.alerter._notifyAlert") as mock_notify2:
            fired = alerter.checkAndNotify()
        self.assertTrue(len(fired) > 0)
        mock_notify2.assert_called()


class TestAlertLoopIntegration(unittest.TestCase):
    """Background alert loop drives checkAndNotify on interval."""

    def setUp(self):
        _reset()

    def tearDown(self):
        _reset()

    def test_loop_is_idempotent_to_double_start(self):
        alerter.startAlertLoop(interval_seconds=0.05)
        time.sleep(0.02)
        thread_ref = alerter._thread
        alerter.startAlertLoop(interval_seconds=0.05)
        self.assertIs(alerter._thread, thread_ref)
        alerter.stopAlertLoop()
        time.sleep(0.15)
        self.assertFalse(thread_ref.is_alive())

    def test_loop_drives_periodic_checks(self):
        call_count = [0]
        orig = alerter.checkAndNotify

        def _counting():
            call_count[0] += 1
            return orig()

        with mock.patch.object(alerter, "checkAndNotify", side_effect=_counting):
            alerter.startAlertLoop(interval_seconds=0.05)
            time.sleep(0.25)
            alerter.stopAlertLoop()
            time.sleep(0.1)

        self.assertGreater(call_count[0], 2, "loop must drive multiple polls within 250ms")

    def test_getNotifiedKeys_empty_initially(self):
        self.assertEqual(alerter.getNotifiedKeys(), {})

    def test_getNotifiedKeys_populated_after_fire(self):
        monitoring.record_execution("wf-keys", False, 1.0)
        with mock.patch("monitoring.alerter._notifyAlert"):
            alerter.checkAndNotify()
        keys = alerter.getNotifiedKeys()
        self.assertIn("low_success_rate", keys)


class TestEmbedStructure(unittest.TestCase):
    """Discord embeds must carry required fields for all alert types."""

    def _assertEmbed(self, embed: dict) -> None:
        for field in ("title", "color", "description", "timestamp", "fields"):
            self.assertIn(field, embed)
        self.assertIsInstance(embed["fields"], list)
        self.assertGreater(len(embed["fields"]), 0)

    def test_low_success_rate_embed(self):
        embed = alerter._buildAlertEmbed(
            "low_success_rate", "rate 80% < 90%", {"value": 0.8, "threshold": SUCCESS_RATE_MIN}
        )
        self._assertEmbed(embed)
        self.assertIn("Low Success Rate", embed["title"])

    def test_high_avg_delay_embed(self):
        embed = alerter._buildAlertEmbed(
            "high_avg_delay", "delay 400s", {"value": 400.0, "threshold": MAX_DELAY_SECONDS}
        )
        self._assertEmbed(embed)
        self.assertIn("High Average Delay", embed["title"])

    def test_max_retries_embed(self):
        embed = alerter._buildAlertEmbed(
            "max_retries_exceeded",
            "wf hit 3 retries",
            {"workflow_id": "wf-z", "retries": MAX_RETRIES},
        )
        self._assertEmbed(embed)
        self.assertIn("Max Retries", embed["title"])

    def test_critical_late_embed(self):
        embed = alerter._buildAlertEmbed(
            "critical_event_late_detection",
            "event detected late",
            {"lag_seconds": 200.0},
        )
        self._assertEmbed(embed)
        self.assertIn("Critical Event", embed["title"])
