"""Tests for adversary.py error handling and logging.

Exercises: empty/garbled browser replies, CDP transient retries with backoff,
non-transient errors (skip retries), Ollama errors, logging emission, and
_parseVerdict validation. All tests are stdlib-only with no network I/O.
"""
import json
import logging
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root is importable regardless of cwd.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

import agents.adversary as adversary


class TestIsCdpTransient(unittest.TestCase):
    def test_timeout(self):
        self.assertTrue(adversary.isCdpTransient(RuntimeError("connection timeout")))

    def test_net_prefix(self):
        self.assertTrue(adversary.isCdpTransient(RuntimeError("net::ERR_INTERNET_DISCONNECTED")))

    def test_connection_reset(self):
        self.assertTrue(adversary.isCdpTransient(RuntimeError("connection reset by peer")))

    def test_non_transient(self):
        self.assertFalse(adversary.isCdpTransient(ValueError("invalid JSON payload")))

    def test_unavailable_5xx(self):
        # Gemini/HTTPS transient signals: service unavailable + 5xx are retryable.
        self.assertTrue(adversary.isCdpTransient(RuntimeError("503 Service Unavailable")))
        self.assertTrue(adversary.isCdpTransient(RuntimeError("deadline exceeded")))


class TestReviewViaBrowserEmptyReply(unittest.TestCase):
    def test_empty_reply_returns_stub(self):
        result = adversary.reviewViaBrowser(
            "test subtask", "heartbeat",
            "some output",
            browser_ask=lambda _: None,
        )
        self.assertEqual(result["verdict"], "approved")
        self.assertTrue(result.get("stub"))

    def test_empty_string_reply_returns_stub(self):
        result = adversary.reviewViaBrowser(
            "test subtask", "heartbeat",
            "some output",
            browser_ask=lambda _: "",
        )
        self.assertTrue(result.get("stub"))


class TestReviewViaBrowserValidReply(unittest.TestCase):
    def _make_browser_ask(self, verdict="approved", concerns=None, notes="ok"):
        payload = json.dumps({"verdict": verdict, "concerns": concerns or [], "notes": notes})
        return lambda _: payload

    def test_approved_verdict(self):
        result = adversary.reviewViaBrowser(
            "my subtask", "uncertainty phrase",
            "output",
            browser_ask=self._make_browser_ask("approved"),
        )
        self.assertEqual(result["verdict"], "approved")
        self.assertFalse(result.get("stub"))
        self.assertEqual(result["surface"], "gemini")

    def test_challenged_verdict(self):
        result = adversary.reviewViaBrowser(
            "my subtask", "heartbeat",
            "output",
            browser_ask=self._make_browser_ask("challenged", ["missed a TODO"]),
        )
        self.assertEqual(result["verdict"], "challenged")
        self.assertIn("missed a TODO", result["concerns"])

    def test_garbled_verdict_word_normalizes(self):
        result = adversary.reviewViaBrowser(
            "s", "r", "o",
            browser_ask=self._make_browser_ask("rejected"),
        )
        self.assertEqual(result["verdict"], "challenged")


class TestReviewViaBrowserNonTransientError(unittest.TestCase):
    def test_non_transient_exception_no_retry(self):
        call_count = 0

        def bad_ask(_):
            nonlocal call_count
            call_count += 1
            raise ValueError("invalid JSON — not transient")

        result = adversary.reviewViaBrowser(
            "s", "r", "o", browser_ask=bad_ask,
        )
        # Non-transient: should only call once (no retries).
        self.assertEqual(call_count, 1)
        self.assertTrue(result.get("stub"))

    def test_invalid_json_no_retry(self):
        call_count = 0

        def bad_json(_):
            nonlocal call_count
            call_count += 1
            return "this is not json at all"

        result = adversary.reviewViaBrowser(
            "s", "r", "o", browser_ask=bad_json,
        )
        self.assertEqual(call_count, 1)
        self.assertTrue(result.get("stub"))


class TestReviewViaBrowserTransientRetry(unittest.TestCase):
    def test_transient_retried_then_stub(self):
        call_count = 0

        def flaky(_):
            nonlocal call_count
            call_count += 1
            raise RuntimeError("connection timeout — transient")

        with patch.object(adversary, "time", wraps=time) as mock_time:
            mock_time.sleep = MagicMock()
            result = adversary.reviewViaBrowser(
                "s", "r", "o", browser_ask=flaky,
            )

        # CDP_MAX_RETRIES=2 means 3 total attempts (0,1,2).
        self.assertEqual(call_count, adversary.CDP_MAX_RETRIES + 1)
        self.assertTrue(result.get("stub"))
        # sleep called between first two failures (not after the final one).
        self.assertEqual(mock_time.sleep.call_count, adversary.CDP_MAX_RETRIES)

    def test_transient_then_success(self):
        call_count = 0
        good_payload = json.dumps({"verdict": "approved", "concerns": [], "notes": "fine"})

        def recover_on_second(_):
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                raise RuntimeError("timeout on first attempt")
            return good_payload

        with patch.object(adversary, "time", wraps=time) as mock_time:
            mock_time.sleep = MagicMock()
            result = adversary.reviewViaBrowser(
                "s", "r", "o", browser_ask=recover_on_second,
            )

        self.assertEqual(result["verdict"], "approved")
        self.assertFalse(result.get("stub"))
        self.assertEqual(call_count, 2)


class TestReviewViaBrowserLogging(unittest.TestCase):
    def test_warning_logged_on_empty_reply(self):
        with self.assertLogs("9to5.adversary", level=logging.WARNING) as cm:
            adversary.reviewViaBrowser("s", "r", "o", browser_ask=lambda _: None)
        self.assertTrue(any("auto-approve" in m for m in cm.output))

    def test_warning_logged_on_exception(self):
        with self.assertLogs("9to5.adversary", level=logging.WARNING) as cm:
            adversary.reviewViaBrowser(
                "s", "r", "o",
                browser_ask=lambda _: (_ for _ in ()).throw(RuntimeError("oops")),
            )
        self.assertTrue(any("auto-approve" in m for m in cm.output))

    def test_info_logged_on_success(self):
        payload = json.dumps({"verdict": "approved", "concerns": [], "notes": "good"})
        with self.assertLogs("9to5.adversary", level=logging.INFO) as cm:
            adversary.reviewViaBrowser("s", "r", "o", browser_ask=lambda _: payload)
        self.assertTrue(any("verdict" in m.lower() or "approved" in m for m in cm.output))


class TestReviewOllamaErrors(unittest.TestCase):
    def test_no_brain_returns_stub(self):
        result = adversary.review("s", "r", "output")
        self.assertTrue(result.get("stub"))
        self.assertEqual(result["verdict"], "approved")

    def test_brain_raises_returns_stub(self):
        def bad_chat(_sys, _usr, **_kw):
            raise ConnectionError("Ollama unreachable")

        result = adversary.review("s", "r", "output", ollama_chat=bad_chat)
        self.assertTrue(result.get("stub"))

    def test_brain_returns_none_returns_stub(self):
        result = adversary.review("s", "r", "output", ollama_chat=lambda *a, **k: None)
        self.assertTrue(result.get("stub"))

    def test_brain_returns_valid_verdict(self):
        content = json.dumps({"verdict": "approved", "concerns": [], "notes": "clean"})
        mock_resp = {"message": {"content": content}}
        result = adversary.review(
            "subtask", "heartbeat", "output",
            ollama_chat=lambda *a, **k: mock_resp,
        )
        self.assertEqual(result["verdict"], "approved")
        self.assertFalse(result.get("stub"))

    def test_brain_challenged_verdict(self):
        content = json.dumps({"verdict": "challenged", "concerns": ["missed test"], "notes": "bad"})
        mock_resp = {"message": {"content": content}}
        result = adversary.review(
            "subtask", "heartbeat", "output",
            ollama_chat=lambda *a, **k: mock_resp,
        )
        self.assertEqual(result["verdict"], "challenged")
        self.assertIn("missed test", result["concerns"])


class TestParseVerdict(unittest.TestCase):
    def test_raises_on_non_json_string(self):
        with self.assertRaises(Exception):
            adversary._parseVerdict("not json", "r", surface="test")

    def test_raises_on_non_dict(self):
        with self.assertRaises(ValueError):
            adversary._parseVerdict([1, 2, 3], "r", surface="test")

    def test_normalizes_challenge_words(self):
        data = {"verdict": "rejected", "concerns": [], "notes": ""}
        rv = adversary._parseVerdict(data, "r", surface="test")
        self.assertEqual(rv["verdict"], "challenged")

    def test_concerns_capped_at_ten(self):
        data = {"verdict": "approved", "concerns": [f"c{i}" for i in range(20)], "notes": ""}
        rv = adversary._parseVerdict(data, "r", surface="test")
        self.assertLessEqual(len(rv["concerns"]), 10)

    def test_surface_preserved(self):
        data = {"verdict": "approved", "concerns": [], "notes": "ok"}
        rv = adversary._parseVerdict(data, "r", surface="browser")
        self.assertEqual(rv["surface"], "browser")


class TestShouldTrigger(unittest.TestCase):
    def test_uncertainty_phrase(self):
        triggered, reason = adversary.shouldTrigger("I'm not sure about this", 0)
        self.assertTrue(triggered)
        self.assertIn("uncertainty", reason)

    def test_pre_pr(self):
        triggered, reason = adversary.shouldTrigger("all good", 0, pre_pr=True)
        self.assertTrue(triggered)
        self.assertIn("pre-PR", reason)

    def test_no_trigger(self):
        triggered, _ = adversary.shouldTrigger("work completed", 1, attempt_count=1)
        self.assertFalse(triggered)


class TestStubReview(unittest.TestCase):
    def test_stub_fields(self):
        rv = adversary._stubReview("heartbeat")
        self.assertEqual(rv["verdict"], "approved")
        self.assertTrue(rv["stub"])
        self.assertIsInstance(rv["concerns"], list)
        self.assertEqual(rv["trigger_reason"], "heartbeat")

    def test_custom_note(self):
        rv = adversary._stubReview("r", note="custom note here")
        self.assertEqual(rv["notes"], "custom note here")
