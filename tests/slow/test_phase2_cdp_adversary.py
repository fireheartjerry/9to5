"""Additional tests for the Phase-2 adversary + browser executor edge cases.

Covers gaps not addressed in test_adversary.py and test_browser_executor.py:
 - output/goal truncation in _buildReviewUser
 - runBrowser generic exception path
 - multiple URLs in prompt expand to multiple goto+extract pairs
 - result dict 'surface' key is always 'browser' (generic browser surface)
 - _parseVerdict with non-dict payload raises ValueError
 - the second-brain stub note mentions the Gemini escalation path
"""
import json
import unittest
from unittest import mock

from agents import adversary, browser_executor


class TestBuildReviewUserTruncation(unittest.TestCase):
    """_buildReviewUser must truncate goal to 1000 chars and output to ADVERSARY_MAX_OUTPUT_CHARS."""

    def test_goal_truncated_to_1000(self):
        long_goal = "G" * 2000
        prompt = adversary._buildReviewUser("title", "reason", "out", long_goal)
        # The goal slice [:1000] must appear in the prompt, excess must not
        self.assertIn("G" * 1000, prompt)
        self.assertNotIn("G" * 1001, prompt)

    def test_output_truncated_to_max_chars(self):
        long_output = "X" * (adversary.ADVERSARY_MAX_OUTPUT_CHARS + 500)
        prompt = adversary._buildReviewUser("title", "reason", long_output, "goal")
        self.assertIn("X" * adversary.ADVERSARY_MAX_OUTPUT_CHARS, prompt)
        self.assertNotIn("X" * (adversary.ADVERSARY_MAX_OUTPUT_CHARS + 1), prompt)

    def test_contains_all_context_fields(self):
        prompt = adversary._buildReviewUser("MY_SUBTASK", "MY_REASON", "MY_OUTPUT", "MY_GOAL")
        self.assertIn("MY_SUBTASK", prompt)
        self.assertIn("MY_REASON", prompt)
        self.assertIn("MY_OUTPUT", prompt)
        self.assertIn("MY_GOAL", prompt)


class TestParseVerdict(unittest.TestCase):
    """_parseVerdict should raise on non-dict payloads."""

    def test_raises_on_list(self):
        with self.assertRaises((ValueError, Exception)):
            adversary._parseVerdict(["approved"], "reason", surface="browser")

    def test_raises_on_string(self):
        with self.assertRaises(Exception):
            adversary._parseVerdict("approved", "reason", surface="browser")

    def test_dict_payload_returns_correct_surface(self):
        rv = adversary._parseVerdict(
            {"verdict": "approved", "concerns": [], "notes": "ok"},
            "heartbeat",
            surface="browser",
        )
        self.assertEqual(rv["surface"], "browser")
        self.assertFalse(rv["stub"])

    def test_empty_concerns_are_filtered(self):
        rv = adversary._parseVerdict(
            {"verdict": "challenged", "concerns": ["real concern", "", "  "]},
            "reason",
            surface="browser",
        )
        self.assertEqual(rv["concerns"], ["real concern"])


class TestRunBrowserGenericException(unittest.TestCase):
    """runBrowser must treat any non-BrowserUnavailable exception as a failed subtask."""

    def test_generic_exception_returns_error_result(self):
        def raise_runtime(actions, **k):
            raise RuntimeError("network timeout")

        with mock.patch.object(browser_executor, "_run_actions", side_effect=raise_runtime):
            res = browser_executor.runBrowser(
                {"surface": "browser", "browser_actions": [{"action": "goto", "url": "x"}]}
            )
        self.assertFalse(res["ok"])
        self.assertTrue(res["is_error"])
        self.assertIn("network timeout", res["stderr"])

    def test_result_surface_key_is_browser(self):
        with mock.patch.object(browser_executor, "_run_actions", return_value="ok"):
            res = browser_executor.runBrowser(
                {"surface": "browser", "browser_actions": [{"action": "goto", "url": "x"}]}
            )
        self.assertEqual(res["surface"], "browser")


class TestMultipleUrlsInPrompt(unittest.TestCase):
    """A prompt with multiple URLs must expand to a goto+extract pair for each."""

    def test_two_urls_produce_four_actions(self):
        captured = {}

        def fake_run(actions, **k):
            captured["actions"] = actions
            return "ok"

        with mock.patch.object(browser_executor, "_run_actions", side_effect=fake_run):
            browser_executor.runBrowser(
                {"surface": "browser",
                 "prompt": "compare https://a.com and https://b.com"}
            )
        kinds = [a["action"] for a in captured["actions"]]
        self.assertEqual(kinds.count("goto"), 2)
        self.assertEqual(kinds.count("extract"), 2)
        urls = [a["url"] for a in captured["actions"] if a["action"] == "goto"]
        self.assertIn("https://a.com", urls)
        self.assertIn("https://b.com", urls)


class TestAdversaryFallbackNote(unittest.TestCase):
    """Stub notes must mention the Phase-2 Gemini escalation path on the no-second-brain path."""

    def test_stub_note_mentions_gemini(self):
        rv = adversary._stubReview("reason")
        self.assertIn("gemini", rv["notes"].lower())

    def test_stub_has_empty_concerns(self):
        rv = adversary._stubReview("any reason")
        self.assertEqual(rv["concerns"], [])
        self.assertTrue(rv["stub"])

    def test_custom_note_overrides_default(self):
        rv = adversary._stubReview("reason", note="custom message")
        self.assertEqual(rv["notes"], "custom message")
