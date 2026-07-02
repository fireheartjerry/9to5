"""Dashboard CV2-mode routing: with DASHBOARD_CV2 on, start()/update() must route to the
Components-V2 transport (not the embed transport) and still pin + persist the message id and
honour the 404/transient recovery contract. discord_bot is monkeypatched -> no network."""
import threading
import unittest

import config
from notifications import dashboard as dash_mod
from notifications import discord_bot as discord


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
