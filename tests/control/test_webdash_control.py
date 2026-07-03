"""Unit tests for webdash._applyControl + _snapshot."""
import re
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from platform_core.runtime.control import ControlBus
from notifications import webdash


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

    def test_token_gates_data_gets(self):
        # The data routes (state/events/raw) disclose goal, work_dir, cost and raw stdout, and
        # are reachable over the public tunnel, so they MUST require the per-run token. Only the
        # bare HTML shell is served openly (it carries no run data).
        import socket
        import urllib.error
        import urllib.request
        config_patch = mock.patch.object(config, "WEB_DASHBOARD", True)
        config_patch.start()
        self.addCleanup(config_patch.stop)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(("127.0.0.1", 0))
            port = s.getsockname()[1]
        url = webdash.startWebDashboard("task-token", port=port)
        self.addCleanup(webdash.stopWebDashboard)
        self.assertTrue(url, f"dashboard failed to bind OS-assigned port {port}")
        token = webdash._CONTROL_TOKEN

        def get(path):
            try:
                return urllib.request.urlopen(url.rstrip("/") + path, timeout=3).status
            except urllib.error.HTTPError as e:
                return e.code

        self.assertEqual(get("/api/state"), 403, "tokenless data GET was not forbidden")
        self.assertEqual(get("/api/state?token=wrong"), 403, "bad token accepted on data GET")
        self.assertEqual(get("/api/raw?sid=st-1"), 403, "tokenless raw GET was not forbidden")
        self.assertEqual(get(f"/api/state?token={token}"), 200, "valid token rejected on data GET")
        # The HTML shell stays open (no run data) so the operator's browser can bootstrap.
        self.assertEqual(get("/"), 200, "HTML shell should be served without a token")

    def test_empty_server_token_always_rejects_post(self):
        # BUG-005: an unset/empty control token must ALWAYS reject control POSTs, never fall
        # through to unconditional allow. startWebDashboard always generates a real random
        # token, so drive a bare handler bound to an explicitly EMPTY token to lock this in.
        import urllib.error
        import urllib.request
        from http.server import ThreadingHTTPServer

        server = ThreadingHTTPServer(("127.0.0.1", 0), webdash._makeHandler("task-empty-token", ""))
        thread = __import__("threading").Thread(target=server.serve_forever, daemon=True)
        thread.start()

        def _stop_server():
            # Stop the serve_forever loop BEFORE closing the socket, then join the thread.
            # Two separate addCleanup calls run LIFO, which would close the listening socket
            # out from under serve_forever's select() -> OSError WinError 10038 in the daemon
            # thread (a flaky PytestUnhandledThreadExceptionWarning under parallel load).
            # Mirror production notifications/webdash.stopWebDashboard: shut down, then close.
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

        self.addCleanup(_stop_server)
        port = server.server_address[1]

        def post(headers):
            req = urllib.request.Request(
                f"http://127.0.0.1:{port}/api/control", data=b'{"action":"pause"}',
                headers={"content-type": "application/json", **headers}, method="POST")
            try:
                return urllib.request.urlopen(req, timeout=3).status
            except urllib.error.HTTPError as e:
                return e.code

        self.assertEqual(post({}), 403, "empty server token allowed a headerless POST")
        self.assertEqual(post({"X-9to5-Token": ""}), 403, "empty server token matched an empty header")
        self.assertEqual(post({"X-9to5-Token": "anything"}), 403,
                         "empty server token allowed an arbitrary client-supplied header")

