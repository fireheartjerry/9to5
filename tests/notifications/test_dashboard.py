"""Unit tests for DiscordDashboard (no live Discord connection)."""
import sys
import tempfile
import threading
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import config
from notifications.dashboard import DiscordDashboard
from notifications import dashboard as dash_mod
from notifications import dashboard as dm
from notifications import discord_bot as discord
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


class TestCouncilTranscriptPost(unittest.TestCase):
    def test_posts_transcript_once_and_records_message_id(self):
        d = DiscordDashboard()
        st = _state()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            transcript_dir = root / "state" / "council_runs" / "run"
            transcript_dir.mkdir(parents=True)
            transcript = transcript_dir / "transcript.md"
            transcript.write_text("GPT: hello\nCerebras: concise\n", encoding="utf-8")
            st.meta["pre_execution_council"] = {"status": "completed"}
            ref = mock.Mock(run_id="abcdef123456", transcript_path=str(transcript))
            with mock.patch.object(config, "DISCORD_DASHBOARD", True), \
                 mock.patch.object(config, "PROJECT_ROOT", root), \
                 mock.patch("notifications.dashboard.discord.postFile", return_value="msg-1") as post:
                d.post_council_transcript(st, ref)
                d.post_council_transcript(st, ref)
            post.assert_called_once()
            self.assertEqual(st.meta["pre_execution_council"]["discord_transcript_message_id"], "msg-1")
            self.assertTrue(any("transcript posted" in e for e in d._eventsSnapshot()))


# ---- merged from test_dashboard_cv2.py ----
# Dashboard CV2-mode routing: with DASHBOARD_CV2 on, start()/update() must route to the
# Components-V2 transport (not the embed transport) and still pin + persist the message id and
# honour the 404/transient recovery contract. discord_bot is monkeypatched -> no network.


class _StubState:
    def __init__(self):
        self.task_id = "deadbeefcafe"
        self.meta = {"goal_raw": "build", "status": "executing", "control_mode": "watch",
                     "started_at": None, "work_dir": "C:/9to5"}
        self.subtasks = [{"subtask_id": "st-001", "title": "a", "status": "in_progress"}]
        self.data = {"notifications": [], "adversary_reviews": []}
        self.saved_events = None
        self.saved_msg_id = None

    def saveDashboardEvents(self, ev):
        self.saved_events = list(ev)

    def setDashboardMessageId(self, mid):
        self.saved_msg_id = mid


def _ids(comps):
    out = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("custom_id"):
                out.append(n["custom_id"])
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for it in n:
                walk(it)

    walk(comps)
    return out


class DashboardCv2Routing(unittest.TestCase):
    def setUp(self):
        self.cv2_create = self.cv2_edit = self.embed_create = self.embed_edit = 0
        self.last_comps = None
        self.pins = []
        self._orig = {}

        def cv2_create(comps, files=None):
            self.cv2_create += 1
            self.last_comps = comps
            return "msg123"

        def cv2_edit(mid, comps, files=None):
            self.cv2_edit += 1
            self.last_comps = comps
            return "ok"

        def embed_create(embed, content=None, components=None):
            self.embed_create += 1
            return "embedmsg"

        def embed_edit(mid, embed, content=None, components=None):
            self.embed_edit += 1
            return "ok"

        def pin(mid):
            self.pins.append(mid)
            return True

        for name, fn in [("createComponentsV2", cv2_create),
                         ("editComponentsV2Result", cv2_edit),
                         ("createMessage", embed_create),
                         ("editMessageResult", embed_edit),
                         ("pinMessage", pin)]:
            self._orig[name] = getattr(discord, name)
            setattr(discord, name, fn)

        self._flags = (config.DASHBOARD_CV2, config.DISCORD_DASHBOARD)
        config.DASHBOARD_CV2 = True
        config.DISCORD_DASHBOARD = True

    def tearDown(self):
        for name, fn in self._orig.items():
            setattr(discord, name, fn)
        config.DASHBOARD_CV2, config.DISCORD_DASHBOARD = self._flags

    def test_start_routes_to_cv2_and_pins(self):
        d = dash_mod.DiscordDashboard()
        st = _StubState()
        d.start(st, "starting", state_lock=threading.Lock())
        self.assertEqual(self.cv2_create, 1)
        self.assertEqual(self.embed_create, 0)
        self.assertEqual(d.message_id, "msg123")
        self.assertIn("msg123", self.pins)
        self.assertEqual(st.saved_msg_id, "msg123")
        self.assertIn("cp_abort", _ids(self.last_comps))   # cockpit carries control buttons

    def test_update_routes_to_cv2_edit(self):
        d = dash_mod.DiscordDashboard()
        d.message_id = "msg123"
        st = _StubState()
        d.update(st, "executing", note="tick")
        self.assertEqual(self.cv2_edit, 1)
        self.assertEqual(self.embed_edit, 0)

    def test_legacy_mode_still_uses_embed(self):
        config.DASHBOARD_CV2 = False
        d = dash_mod.DiscordDashboard()
        st = _StubState()
        d.start(st, "starting", state_lock=threading.Lock())
        self.assertEqual(self.embed_create, 1)
        self.assertEqual(self.cv2_create, 0)


# ---- merged from test_cockpit_throttle.py ----
# P1 hardening: the cockpit hero-image upload is throttled to <=1 per COCKPIT_IMAGE_MIN_INTERVAL,
# so the every-4s pause loop can't drive a multipart-upload rate-limit storm. Text-CV2 still flows.


class _State:
    meta = {"goal_raw": "Build the lab", "status": "executing", "control_mode": "watch",
            "started_at": None, "work_dir": "C:/9to5"}
    subtasks = [{"subtask_id": "st-001", "title": "a", "status": "in_progress"}]
    data = {"notifications": [], "adversary_reviews": []}


class CockpitImageThrottle(unittest.TestCase):
    def setUp(self):
        self._flags = (config.VISUALS_ENABLED, config.DASHBOARD_CV2, config.COCKPIT_IMAGE_MIN_INTERVAL)
        config.VISUALS_ENABLED = True
        config.DASHBOARD_CV2 = True
        config.COCKPIT_IMAGE_MIN_INTERVAL = 30

    def tearDown(self):
        config.VISUALS_ENABLED, config.DASHBOARD_CV2, config.COCKPIT_IMAGE_MIN_INTERVAL = self._flags

    def test_first_includes_image_then_throttled(self):
        d = dm.DiscordDashboard()
        _, files1 = d._cockpit(_State(), "executing")
        self.assertIsNotNone(files1)                      # first render uploads the image
        self.assertEqual(files1[0][0], "cockpit.png")

        _, files2 = d._cockpit(_State(), "executing")
        self.assertIsNone(files2)                         # rapid second tick: throttled (text-CV2 only)

    def test_refreshes_after_interval(self):
        d = dm.DiscordDashboard()
        d._cockpit(_State(), "executing")                 # primes _last_image_ts
        d._last_image_ts -= 31                            # simulate >interval elapsed
        _, files = d._cockpit(_State(), "executing")
        self.assertIsNotNone(files)                       # image refreshes after the interval

    def test_text_cockpit_always_built(self):
        d = dm.DiscordDashboard()
        comps, _ = d._cockpit(_State(), "executing")
        # the CV2 container is always present regardless of image throttling
        self.assertEqual(comps[0]["type"], 17)

    def test_disabled_never_uploads(self):
        config.VISUALS_ENABLED = False
        d = dm.DiscordDashboard()
        _, files = d._cockpit(_State(), "executing")
        self.assertIsNone(files)
