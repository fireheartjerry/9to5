"""Unit tests for webdash._applyControl + _snapshot."""
import re
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import config
from platform_core.runtime.control import ControlBus
from notifications import webdash
from state.task import TaskState


class TestApplyControl(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self._patch = mock.patch.object(config, "CONTROL_DIR", self.dir)
        self._patch.start()
        self.tid = "task-web"

    def tearDown(self):
        self._patch.stop()
        for p in self.dir.glob("*"):
            p.unlink()
        self.dir.rmdir()

    def test_abort_pause_resume(self):
        self.assertTrue(webdash._applyControl(self.tid, "abort", None)["ok"])
        self.assertTrue(ControlBus(self.tid).isAbort())
        webdash._applyControl(self.tid, "pause", None)
        self.assertTrue(ControlBus(self.tid).isPaused())
        webdash._applyControl(self.tid, "resume", None)
        self.assertFalse(ControlBus(self.tid).isPaused())

    def test_approve_valid_gate(self):
        bus = ControlBus(self.tid)
        bus.setPendingGate("plan")
        res = webdash._applyControl(self.tid, "approve", None)
        self.assertTrue(res["ok"])
        self.assertEqual(res["gate"], "plan")
        self.assertEqual(ControlBus(self.tid).getDecision("plan"), "approve")

    def test_approve_unknown_gate_is_rejected(self):
        res = webdash._applyControl(self.tid, "approve", "not-a-gate")
        self.assertFalse(res["ok"])
        # no stray decision key was written
        self.assertNotIn("not-a-gate", ControlBus(self.tid).load()["decisions"])

    def test_approve_without_pending_gate(self):
        res = webdash._applyControl(self.tid, "approve", None)
        self.assertFalse(res["ok"])

    def test_skip_queues_op(self):
        self.assertTrue(webdash._applyControl(self.tid, "skip", "st-002")["ok"])
        self.assertEqual(ControlBus(self.tid).drainOps(),
                         [{"op": "skip", "subtask_id": "st-002"}])

    def test_unknown_action_reports_error(self):
        res = webdash._applyControl(self.tid, "frobnicate", None)
        self.assertFalse(res["ok"])
        self.assertIn("unknown", res["error"])

    def test_incomplete_skip_reports_error(self):
        res = webdash._applyControl(self.tid, "skip", None)
        self.assertFalse(res["ok"])


class TestControlToken(unittest.TestCase):
    """The /api/control POST endpoint must require the per-run token embedded in the served page,
    so another local process / a cross-origin page can't drive a live run."""

    def test_token_gates_post(self):
        import socket
        import urllib.request
        import urllib.error
        config_patch = mock.patch.object(config, "WEB_DASHBOARD", True)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        # startWebDashboard coerces port=0 to config.WEB_DASHBOARD_PORT (`port or ...`) and
        # builds the URL from the requested port, so true port=0 flow-through is not possible
        # without changing the code under test. Probe the OS for a free ephemeral port instead
        # (tiny close-then-rebind race accepted) so xdist workers never collide on a fixed port.
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        url = webdash.startWebDashboard("task-token", port=port)
        self.addCleanup(webdash.stopWebDashboard)
        self.assertTrue(url, f"dashboard failed to bind OS-assigned port {port}")
        page = urllib.request.urlopen(url, timeout=3).read().decode()
        m = re.search(r'const __T="([^"]+)"', page)
        self.assertTrue(m and m.group(1) != "__WEBDASH_TOKEN__", "page did not embed a real token")
        token = m.group(1)

        def post(headers):
            req = urllib.request.Request(
                url + "api/control", data=b'{"action":"pause"}',
                headers={"content-type": "application/json", **headers}, method="POST")
            try:
                return urllib.request.urlopen(req, timeout=3).status
            except urllib.error.HTTPError as e:
                return e.code

        self.assertEqual(post({}), 403, "tokenless control POST was not forbidden")
        self.assertEqual(post({"X-9to5-Token": "wrong"}), 403, "bad token was accepted")
        self.assertEqual(post({"X-9to5-Token": token}), 200, "valid token was rejected")
