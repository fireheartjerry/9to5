"""Unit tests for DiscordDashboard (no live Discord connection)."""
import threading
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import config
from notifications.dashboard import DiscordDashboard
from state.task import TaskState


def _state():
    st = TaskState.create("test goal", 1.0)
    st.meta["status"] = "executing"
    st.addSubtask("first", "do x")
    return st


class TestElapsed(unittest.TestCase):
    def test_recent_seconds(self):
        started = (datetime.now() - timedelta(seconds=30)).isoformat()
        result = DiscordDashboard._elapsed(started)
        self.assertIn("s", result)

    def test_minutes(self):
        started = (datetime.now() - timedelta(minutes=5)).isoformat()
        result = DiscordDashboard._elapsed(started)
        self.assertIn("m", result)

    def test_hours_and_minutes(self):
        started = (datetime.now() - timedelta(hours=2, minutes=15)).isoformat()
        result = DiscordDashboard._elapsed(started)
        self.assertIn("h", result)
        self.assertIn("m", result)

    def test_none_returns_dash(self):
        self.assertEqual(DiscordDashboard._elapsed(None), "—")

    def test_garbage_returns_dash(self):
        self.assertEqual(DiscordDashboard._elapsed("not-a-date"), "—")

    def test_future_timestamp_returns_zero_seconds(self):
        future = (datetime.now() + timedelta(hours=1)).isoformat()
        result = DiscordDashboard._elapsed(future)
        self.assertEqual(result, "0s")


class TestEventDeque(unittest.TestCase):
    def test_event_appended(self):
        d = DiscordDashboard()
        d.event("hello")
        snap = d._eventsSnapshot()
        self.assertEqual(len(snap), 1)
        self.assertIn("hello", snap[0])

    def test_snapshot_is_a_copy(self):
        d = DiscordDashboard()
        d.event("a")
        snap = d._eventsSnapshot()
        snap.append("injected")
        self.assertEqual(len(d._eventsSnapshot()), 1)

    def test_deque_maxlen_8(self):
        d = DiscordDashboard()
        for i in range(12):
            d.event(f"evt{i}")
        self.assertEqual(len(d._eventsSnapshot()), 8)

    def test_thread_safety(self):
        d = DiscordDashboard()
        errors = []

        def writer():
            try:
                for _ in range(50):
                    d.event("x")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertEqual(errors, [])


class TestNoOpWhenDisabled(unittest.TestCase):
    def _patched(self):
        return mock.patch.object(config, "DISCORD_DASHBOARD", False)

    def test_start_noop(self):
        d = DiscordDashboard()
        with self._patched(), mock.patch("notifications.discord_bot.createMessage") as m:
            d.start(_state())
        m.assert_not_called()

    def test_update_noop(self):
        d = DiscordDashboard()
        with self._patched(), mock.patch("notifications.discord_bot.editMessage") as m:
            d.update(_state(), "executing")
        m.assert_not_called()

    def test_unpin_noop(self):
        d = DiscordDashboard()
        d.message_id = "123"
        with self._patched(), mock.patch("notifications.discord_bot.unpinMessage") as m:
            d.unpin()
        m.assert_not_called()


class TestEmbedBuilding(unittest.TestCase):
    def test_embed_has_required_keys(self):
        d = DiscordDashboard()
        st = _state()
        with mock.patch("notifications.discord_bot.statusColor", return_value=0), \
             mock.patch("notifications.discord_bot.progressBar", return_value="bar"), \
             mock.patch("notifications.discord_bot.subtaskTracker", return_value="tracker"), \
             mock.patch("notifications.discord_bot.effortBar", return_value="effort"):
            embed = d._embed(st, "executing")
        self.assertIn("title", embed)
        self.assertIn("executing", embed["title"])
        self.assertIn("fields", embed)
        self.assertIn("footer", embed)

    def test_embed_title_uses_phase_emoji(self):
        d = DiscordDashboard()
        st = _state()
        with mock.patch("notifications.discord_bot.statusColor", return_value=0), \
             mock.patch("notifications.discord_bot.progressBar", return_value=""), \
             mock.patch("notifications.discord_bot.subtaskTracker", return_value=""), \
             mock.patch("notifications.discord_bot.effortBar", return_value=""):
            embed = d._embed(st, "complete")
        self.assertIn("✅", embed["title"])

    def test_update_stores_effort_and_model(self):
        d = DiscordDashboard()
        with mock.patch.object(config, "DISCORD_DASHBOARD", True), \
             mock.patch("notifications.discord_bot.statusColor", return_value=0), \
             mock.patch("notifications.discord_bot.progressBar", return_value=""), \
             mock.patch("notifications.discord_bot.subtaskTracker", return_value=""), \
             mock.patch("notifications.discord_bot.effortBar", return_value=""), \
             mock.patch("notifications.discord_bot.editMessage", return_value=True), \
             mock.patch("notifications.branding.controlPanelRow", return_value=[]):
            d.message_id = "abc"
            d.update(_state(), "executing", effort="high", model="claude-opus")
        self.assertEqual(d.effort, "high")
        self.assertEqual(d.model, "claude-opus")


if __name__ == "__main__":
    unittest.main()
