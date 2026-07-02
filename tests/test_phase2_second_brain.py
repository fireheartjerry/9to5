"""Offline unit tests for the Phase-2 Gemini second-brain stack.

No network / no Ollama: the Gemini transport is mocked behind ``browser_ask`` callables, and the
brains are mocked. Covers the rich-verdict parse, second_brain's Gemini -> Ollama -> stub fallback
chain + severity gating, and trust telemetry. The Gemini driver's own pure logic is covered in
tests/test_gemini_driver.py.
"""
import json
import unittest
from unittest import mock

import config
from agents import adversary, gemini_driver, second_brain


# --- rich verdict parsing -------------------------------------------------------------------
class TestRichVerdict(unittest.TestCase):
    def test_defaults_when_fields_missing(self):
        rv = adversary._parseVerdict({"verdict": "approved", "concerns": []}, "r", surface="gemini")
        self.assertEqual(rv["severity"], "none")
        self.assertEqual(rv["must_fix"], [])
        self.assertIsNone(rv["confidence"])
        self.assertEqual(rv["review_type"], "subtask")

    def test_rich_fields_parsed(self):
        payload = {"verdict": "challenged", "severity": "high",
                   "must_fix": ["add a test", ""], "suggested_fix": "wrap in try",
                   "confidence": 0.8, "concerns": ["no test"]}
        rv = adversary._parseVerdict(payload, "r", surface="gemini", review_type="pre_pr_diff")
        self.assertEqual(rv["severity"], "high")
        self.assertEqual(rv["must_fix"], ["add a test"])      # empty filtered
        self.assertEqual(rv["confidence"], 0.8)
        self.assertEqual(rv["review_type"], "pre_pr_diff")

    def test_challenged_defaults_to_medium_severity(self):
        rv = adversary._parseVerdict({"verdict": "rejected", "concerns": ["x"]}, "r", surface="gemini")
        self.assertEqual(rv["verdict"], "challenged")
        self.assertEqual(rv["severity"], "medium")

    def test_systemFor_each_type_has_schema(self):
        for rt in second_brain.REVIEW_TYPES:
            self.assertIn("verdict", adversary.systemFor(rt))


# --- second_brain dispatch chain ------------------------------------------------------------
class TestConsultChain(unittest.TestCase):
    def setUp(self):
        self._p = mock.patch.object(config, "GEMINI_ENABLED", True)
        self._p.start()

    def tearDown(self):
        mock.patch.stopall()

    def test_gpt_tier_when_gemini_ok(self):
        def ask(m): return json.dumps({"verdict": "approved", "concerns": []})
        rv = second_brain.consult("subtask", title="t", trigger_reason="r", content="out",
                                   browser_ask=ask, session_ok=True, worth=True)
        self.assertEqual(rv["tier"], "gpt")          # "gpt" denotes the external strong critic
        self.assertFalse(rv["stub"])
        self.assertFalse(rv["session_dead"])

    def test_falls_to_ollama_when_gemini_stubs(self):
        # browser_ask returns junk -> reviewViaBrowser stubs -> chain must try Ollama.
        def chat(system, user, *, want_json=False): return {
            "message": {"content": json.dumps({"verdict": "approved", "concerns": []})}}
        rv = second_brain.consult("subtask", title="t", trigger_reason="r", content="out",
                                   browser_ask=lambda m: "not json", ollama_chat=chat,
                                   session_ok=True, worth=True)
        self.assertEqual(rv["tier"], "ollama")
        self.assertFalse(rv["stub"])

    def test_fatal_error_sets_session_dead(self):
        def boom(m):
            raise gemini_driver.GeminiAuthError("invalid api key")
        rv = second_brain.consult("subtask", title="t", trigger_reason="r", content="out",
                                   browser_ask=boom, ollama_chat=None, session_ok=True, worth=True)
        self.assertTrue(rv["session_dead"])
        self.assertTrue(rv["stub"])          # no ollama_chat -> stub tier
        self.assertEqual(rv["tier"], "stub")

    def test_skips_gpt_when_not_worth(self):
        called = {"n": 0}

        def ask(m):
            called["n"] += 1
            return json.dumps({"verdict": "approved", "concerns": []})
        rv = second_brain.consult("subtask", title="t", trigger_reason="r", content="x",
                                   browser_ask=ask, session_ok=True, worth=False)
        self.assertEqual(called["n"], 0)     # cost guard kept Gemini out
        self.assertNotEqual(rv["tier"], "gpt")


class TestIsBlocking(unittest.TestCase):
    def test_approved_never_blocks(self):
        self.assertFalse(second_brain.is_blocking({"verdict": "approved", "tier": "gpt"}))

    def test_non_gpt_challenge_always_blocks(self):
        self.assertTrue(second_brain.is_blocking({"verdict": "challenged", "tier": "ollama"}))
        self.assertTrue(second_brain.is_blocking({"verdict": "challenged"}))  # missing tier => conservative

    def test_gpt_severity_gating(self):
        with mock.patch.object(config, "ADVERSARY_BLOCKING_SEVERITY", "high"):
            self.assertTrue(second_brain.is_blocking(
                {"verdict": "challenged", "tier": "gpt", "severity": "high"}))
            self.assertFalse(second_brain.is_blocking(
                {"verdict": "challenged", "tier": "gpt", "severity": "low"}))


# --- trust telemetry ------------------------------------------------------------------------
class TestTrustTelemetry(unittest.TestCase):
    def test_record_and_summary(self):
        import tempfile
        from pathlib import Path
        from learning import adversary_trust
        with tempfile.TemporaryDirectory() as d:
            log = Path(d) / "trust.jsonl"
            with mock.patch.object(config, "ADVERSARY_TRUST_LOG", log):
                adversary_trust.record("subtask", {"verdict": "approved", "severity": "none"}, tier="gpt")
                adversary_trust.record("subtask", {"verdict": "challenged", "severity": "high"},
                                       tier="gpt", upheld=True)
                s = adversary_trust.summary()
            self.assertEqual(s["consults"], 2)
            self.assertEqual(s["gpt"], 2)
            self.assertEqual(s["challenges"], 1)
            self.assertEqual(s["upheld_rate"], 1.0)


if __name__ == "__main__":
    unittest.main()
