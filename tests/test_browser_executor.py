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


class TestChatGPTRouting(unittest.TestCase):
    """chatgpt.com CDP routing used by the Phase-2 Adversary brain."""

    def tearDown(self):
        mock.patch.stopall()

    def test_actions_recipe_send_then_read(self):
        actions = browser_executor.chatgptActions("hello there")
        kinds = [a["action"] for a in actions]
        self.assertEqual(kinds[0], "goto")          # open the chat
        self.assertIn("type", kinds)                # type the message
        self.assertIn("press", kinds)               # submit
        self.assertEqual(kinds[-1], "extract")      # read the reply last
        typed = next(a for a in actions if a["action"] == "type")
        self.assertEqual(typed["text"], "hello there")
        self.assertEqual(actions[0]["url"], browser_executor.CHATGPT_URL)

    def test_reply_parser_pulls_last_extract_block(self):
        transcript = ("goto https://chatgpt.com/ -> 'ChatGPT'\n"
                      "type into #prompt-textarea\n"
                      "press Enter on #prompt-textarea\n"
                      "extract [data-message-author-role='assistant']:\n"
                      "the assistant said this\nand more")
        self.assertEqual(browser_executor._replyFromTranscript(transcript),
                         "the assistant said this\nand more")

    def test_ask_chatgpt_routes_through_runner_and_returns_reply(self):
        captured = {}

        def fake_runner(spec, **k):
            captured["spec"] = spec
            return {"ok": True, "stdout": "extract sel:\nGPT REPLY"}

        reply = browser_executor.askChatGPT("question?", runner=fake_runner)
        self.assertEqual(reply, "GPT REPLY")
        self.assertEqual(captured["spec"]["surface"], "browser")
        self.assertTrue(captured["spec"]["browser_actions"])

    def test_ask_chatgpt_returns_none_on_failed_run(self):
        def fake_runner(spec, **k):
            return {"ok": False, "is_error": True, "stderr": "no playwright"}
        self.assertIsNone(browser_executor.askChatGPT("q", runner=fake_runner))

    def test_ask_chatgpt_returns_none_on_empty_reply(self):
        def fake_runner(spec, **k):
            return {"ok": True, "stdout": "goto x -> 'X'"}   # no extract block
        self.assertIsNone(browser_executor.askChatGPT("q", runner=fake_runner))


if __name__ == "__main__":
    unittest.main()
