"""Tests for the browser (CDP / Layer 1) executor + orchestrator surface dispatch."""
import unittest
from unittest import mock

import config
from agents import browser_executor, executor


class TestBrowserExecutor(unittest.TestCase):
    def tearDown(self):
        mock.patch.stopall()

    def test_result_matches_runclaude_contract(self):
        with mock.patch.object(browser_executor, "_run_actions", return_value="goto x -> 'X'"):
            res = browser_executor.runBrowser(
                {"surface": "browser", "browser_actions": [{"action": "goto", "url": "http://x"}]})
        # Same keys the orchestrator reads from a Claude result.
        for k in ("ok", "returncode", "stdout", "stderr", "is_error", "spec", "profile"):
            self.assertIn(k, res)
        self.assertTrue(res["ok"])
        self.assertFalse(res["is_error"])
        self.assertIn("goto x", res["stdout"])

    def test_url_prompt_auto_expands_to_actions(self):
        captured = {}

        def fake_run(actions, **k):
            captured["actions"] = actions
            return "ok"

        with mock.patch.object(browser_executor, "_run_actions", side_effect=fake_run):
            browser_executor.runBrowser({"surface": "browser",
                                         "prompt": "summarize https://example.com/page"})
        kinds = [a["action"] for a in captured["actions"]]
        self.assertIn("goto", kinds)
        self.assertIn("extract", kinds)

    def test_no_actions_is_clean_error(self):
        res = browser_executor.runBrowser({"surface": "browser", "prompt": "do something vague"})
        self.assertFalse(res["ok"])
        self.assertTrue(res["is_error"])
        self.assertIn("browser_actions", res["stderr"])

    def test_unavailable_backend_degrades(self):
        def raise_unavailable(actions, **k):
            raise browser_executor.BrowserUnavailable("no playwright")

        with mock.patch.object(browser_executor, "_run_actions", side_effect=raise_unavailable):
            res = browser_executor.runBrowser({"browser_actions": [{"action": "goto", "url": "x"}]})
        self.assertFalse(res["ok"])
        self.assertTrue(res["is_error"])           # failed subtask, not a crash
        self.assertIn("playwright", res["stderr"])


class TestSurfaceContractAndDispatch(unittest.TestCase):
    def tearDown(self):
        mock.patch.stopall()

    def test_normalize_spec_has_surface_defaults(self):
        spec = executor.normalizeSpec("just a prompt")
        self.assertEqual(spec["surface"], "terminal")
        self.assertEqual(spec["browser_actions"], [])

    def test_dispatcher_routes_browser_when_enabled(self):
        import orchestrator
        orch = orchestrator.Orchestrator.__new__(orchestrator.Orchestrator)  # no full init
        orch._run_claude = lambda *a, **k: {"ok": True}
        with mock.patch.object(config, "BROWSER_LAYER_ENABLED", True):
            hands = orch._selectExecutor({"surface": "browser"})
        self.assertIs(hands, browser_executor.runBrowser)

    def test_dispatcher_defaults_to_terminal(self):
        import orchestrator
        orch = orchestrator.Orchestrator.__new__(orchestrator.Orchestrator)
        sentinel = lambda *a, **k: {"ok": True}
        orch._run_claude = sentinel
        with mock.patch.object(config, "BROWSER_LAYER_ENABLED", True):
            self.assertIs(orch._selectExecutor({"surface": "terminal"}), sentinel)
        with mock.patch.object(config, "BROWSER_LAYER_ENABLED", False):
            self.assertIs(orch._selectExecutor({"surface": "browser"}), sentinel)  # gated off


class TestGeminiRouting(unittest.TestCase):
    """Gemini second-brain shim used by the Adversary (google-genai SDK transport)."""

    def tearDown(self):
        mock.patch.stopall()

    def test_ask_gemini_runner_is_called_directly_with_message(self):
        captured = {}

        def fake_runner(message):
            captured["message"] = message
            return "GEMINI REPLY"

        reply = browser_executor.askGemini("question?", runner=fake_runner)
        self.assertEqual(reply, "GEMINI REPLY")
        self.assertEqual(captured["message"], "question?")

    def test_ask_gemini_runner_can_return_none(self):
        self.assertIsNone(browser_executor.askGemini("q", runner=lambda m: None))

    def test_ask_gemini_delegates_to_session_ask_without_runner(self):
        with mock.patch.object(browser_executor, "sessionAsk", return_value="from session") as m:
            reply = browser_executor.askGemini("q", expect_json=True)
        self.assertEqual(reply, "from session")
        m.assert_called_once_with("q", expect_json=True)
