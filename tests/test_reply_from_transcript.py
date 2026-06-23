"""Unit tests for _replyFromTranscript edge cases."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from agents.browser_executor import _replyFromTranscript

SELECTOR = "[data-message-author-role='assistant']"


class TestReplyFromTranscript(unittest.TestCase):
    def test_normal_full_block(self):
        transcript = (
            "goto https://chatgpt.com/\n"
            f"extract {SELECTOR}:\nHello world"
        )
        self.assertEqual(_replyFromTranscript(transcript), "Hello world")

    def test_multiline_reply(self):
        transcript = f"extract {SELECTOR}:\nline one\nline two"
        self.assertEqual(_replyFromTranscript(transcript), "line one\nline two")

    def test_last_extract_wins(self):
        transcript = (
            f"extract {SELECTOR}:\nfirst reply\n"
            f"extract {SELECTOR}:\nsecond reply"
        )
        self.assertEqual(_replyFromTranscript(transcript), "second reply")

    def test_no_extract_returns_empty(self):
        self.assertEqual(_replyFromTranscript("goto https://chatgpt.com/\n"), "")

    def test_none_input_returns_empty(self):
        self.assertEqual(_replyFromTranscript(None), "")

    def test_no_newline_after_selector_returns_selector(self):
        # edge case: transcript truncated immediately after selector line
        transcript = f"extract {SELECTOR}:"
        result = _replyFromTranscript(transcript)
        self.assertNotEqual(result, "", "should return selector, not empty string")
        self.assertIn("assistant", result)

    def test_no_newline_selector_without_trailing_colon(self):
        transcript = f"extract {SELECTOR}"
        result = _replyFromTranscript(transcript)
        self.assertNotEqual(result, "")
        self.assertIn("assistant", result)

    def test_empty_string_returns_empty(self):
        self.assertEqual(_replyFromTranscript(""), "")


if __name__ == "__main__":
    unittest.main()
