"""Unit tests for DiscordDashboard (no live Discord connection)."""
import sys
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from notifications.dashboard import DiscordDashboard
from state.task import TaskState


def _state():
    st = TaskState.create("test goal", 1.0)
    st.meta["status"] = "executing"
    st.addSubtask("first", "do x")
    return st


class TestRecreateOnlyOn404(unittest.TestCase):
    """A transient Discord failure (429 breaker armed / timeout) must NOT recreate the dashboard
    (which would spawn a duplicate pinned embed and burn the one-shot guard); only a genuine 404 does."""
    def _dash(self):
        d = DiscordDashboard()
        d.message_id = "123"
        return d

    def test_transient_edit_does_not_recreate(self):
        d = self._dash()
        with mock.patch.object(config, "DISCORD_DASHBOARD", True), \
                mock.patch.object(config, "DASHBOARD_CV2", False), \
                mock.patch.object(d, "_embed", return_value={}), \
                mock.patch("notifications.dashboard.discord.editMessageResult", return_value="transient") as ed, \
                mock.patch("notifications.dashboard.discord.createMessage") as create:
            d.update(mock.Mock(), "executing")
        ed.assert_called_once()
        create.assert_not_called()
        self.assertEqual(d.message_id, "123")   # unchanged
        self.assertFalse(d._recreated)          # one-shot NOT burned

    def test_genuine_404_recreates_once(self):
        d = self._dash()
        with mock.patch.object(config, "DISCORD_DASHBOARD", True), \
                mock.patch.object(config, "DASHBOARD_CV2", False), \
                mock.patch.object(d, "_embed", return_value={}), \
                mock.patch("notifications.dashboard.discord.editMessageResult", return_value="not_found"), \
                mock.patch("notifications.dashboard.discord.createMessage", return_value="456") as create, \
                mock.patch("notifications.dashboard.discord.pinMessage"):
            d.update(mock.Mock(), "executing")
        create.assert_called_once()
        self.assertEqual(d.message_id, "456")
        self.assertTrue(d._recreated)


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

    def test_deque_maxlen_caps_recent_events(self):
        d = DiscordDashboard()
        for i in range(20):
            d.event(f"e{i}x")   # unique tokens (e0x..e19x); no substring overlap between them
        snap = d._eventsSnapshot()
        # the "Recent events" ring is bounded (deque maxlen=10) and keeps the NEWEST. Events are
        # stored timestamp-prefixed, so match on the joined text, not exact list membership.
        self.assertEqual(len(snap), 10)
        joined = "\n".join(snap)
        self.assertIn("e19x", joined)       # newest kept
        self.assertNotIn("e0x", joined)     # oldest evicted

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

    def test_embed_title_uses_phase(self):
        d = DiscordDashboard()
        st = _state()
        with mock.patch("notifications.discord_bot.statusColor", return_value=0), \
             mock.patch("notifications.discord_bot.progressBar", return_value=""), \
             mock.patch("notifications.discord_bot.subtaskTracker", return_value=""), \
             mock.patch("notifications.discord_bot.effortBar", return_value=""):
            embed = d._embed(st, "complete")
        self.assertIn("complete", embed["title"])     # clean phase title, no emoji
        self.assertIn("9TO5", embed["title"])

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


class TestEventPersistence(unittest.TestCase):
    def test_start_loads_persisted_events(self):
        """Events stored in state.data are prepended into the deque on start()."""
        d = DiscordDashboard()
        st = _state()
        st.data["dashboard_events"] = ["`09:00` old event"]
        with mock.patch.object(config, "DISCORD_DASHBOARD", True), \
             mock.patch.object(d, "_embed", return_value={}), \
             mock.patch("notifications.dashboard.discord.editMessageResult", return_value="not_found"), \
             mock.patch("notifications.dashboard.discord.createMessage", return_value="999"), \
             mock.patch("notifications.dashboard.discord.pinMessage"), \
             mock.patch.object(st, "saveDashboardEvents"):
            d.start(st)
        snap = d._eventsSnapshot()
        self.assertTrue(any("old event" in e for e in snap))

    def test_start_saves_events_to_state(self):
        """start() persists the updated event ring back to state."""
        d = DiscordDashboard()
        st = _state()
        with mock.patch.object(config, "DISCORD_DASHBOARD", True), \
             mock.patch.object(d, "_embed", return_value={}), \
             mock.patch("notifications.dashboard.discord.editMessageResult", return_value="not_found"), \
             mock.patch("notifications.dashboard.discord.createMessage", return_value="999"), \
             mock.patch("notifications.dashboard.discord.pinMessage"), \
             mock.patch.object(st, "saveDashboardEvents") as save_ev:
            d.start(st)
        save_ev.assert_called_once()
        saved = save_ev.call_args[0][0]
        self.assertTrue(any("run started" in e for e in saved))

    def test_update_persists_events_to_state(self):
        """update() saves the event ring (including the new event) to state."""
        d = DiscordDashboard()
        d.message_id = "abc"
        st = _state()
        with mock.patch.object(config, "DISCORD_DASHBOARD", True), \
             mock.patch.object(d, "_embed", return_value={}), \
             mock.patch("notifications.dashboard.discord.editMessageResult", return_value="ok"), \
             mock.patch("notifications.branding.controlPanelRow", return_value=[]), \
             mock.patch.object(st, "saveDashboardEvents") as save_ev:
            d.update(st, "executing", note="step done")
        save_ev.assert_called()
        saved = save_ev.call_args[0][0]
        self.assertTrue(any("step done" in e for e in saved))

    def test_update_persists_even_without_note(self):
        """update() always calls saveDashboardEvents, not only when there is a note."""
        d = DiscordDashboard()
        d.message_id = "abc"
        st = _state()
        with mock.patch.object(config, "DISCORD_DASHBOARD", True), \
             mock.patch.object(d, "_embed", return_value={}), \
             mock.patch("notifications.dashboard.discord.editMessageResult", return_value="ok"), \
             mock.patch("notifications.branding.controlPanelRow", return_value=[]), \
             mock.patch.object(st, "saveDashboardEvents") as save_ev:
            d.update(st, "executing")
        save_ev.assert_called()

    def test_persistence_noop_when_discord_disabled(self):
        """When DISCORD_DASHBOARD is False, start() exits before touching events."""
        d = DiscordDashboard()
        st = _state()
        st.data["dashboard_events"] = ["`09:00` old event"]
        with mock.patch.object(config, "DISCORD_DASHBOARD", False), \
             mock.patch.object(st, "saveDashboardEvents") as save_ev:
            d.start(st)
        save_ev.assert_not_called()
        self.assertEqual(len(d._eventsSnapshot()), 0)
