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
    """B14: the control token must never be served in the page (it would leak over the public
    tunnel). The served page is view-only; /api/control requires the console-only control token."""

    def test_page_never_serves_control_token(self):
        import urllib.request
        config_patch = mock.patch.object(config, "WEB_DASHBOARD", True)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        url = webdash.startWebDashboard("task-token", port=8791)
        if not url:
            self.skipTest("could not bind the dashboard port")
        self.addCleanup(webdash.stopWebDashboard)
        token = webdash._CONTROL_TOKEN
        self.assertTrue(token, "no control token was generated")
        page = urllib.request.urlopen(url, timeout=3).read().decode()
        # The real control token must not appear anywhere in the served HTML.
        self.assertNotIn(token, page, "control token leaked into served page HTML")
        # The token placeholder must be blanked, not left unsubstituted with a live token.
        m = re.search(r'const __T="([^"]*)"', page)
        self.assertTrue(m, "token placeholder missing from page")
        self.assertEqual(m.group(1), "", "page embedded a control token")

    def test_token_gates_post(self):
        import urllib.request
        import urllib.error
        config_patch = mock.patch.object(config, "WEB_DASHBOARD", True)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        url = webdash.startWebDashboard("task-token", port=8791)
        if not url:
            self.skipTest("could not bind the dashboard port")
        self.addCleanup(webdash.stopWebDashboard)
        token = webdash._CONTROL_TOKEN

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
        self.assertEqual(post({"X-9to5-Token": token}), 200, "valid console token was rejected")


if __name__ == "__main__":
    unittest.main()
