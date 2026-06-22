"""Unit tests for the Adversary reviewer (trigger logic + Ollama-backed critique)."""
import json
import unittest

import config
from agents import adversary


def _fakeChat(payload):
    """Return an ollama_chat stand-in that yields ``payload`` as the JSON content."""
    def _chat(system, user, *, want_json=False):
        return {"message": {"content": json.dumps(payload)}}
    return _chat


class TestShouldTrigger(unittest.TestCase):
    def test_uncertainty_phrase(self):
        phrase = config.ADVERSARY_TRIGGER_PHRASES[0]
        trig, reason = adversary.shouldTrigger(f"... {phrase} ...", subtask_position=1)
        self.assertTrue(trig)
        self.assertIn(phrase, reason)

    def test_max_attempts(self):
        trig, reason = adversary.shouldTrigger("all good", 1, attempt_count=config.MAX_SUBTASK_ATTEMPTS)
        self.assertTrue(trig)
        self.assertIn("attempts", reason)

    def test_pre_pr(self):
        trig, reason = adversary.shouldTrigger("", 1, pre_pr=True)
        self.assertTrue(trig)
        self.assertEqual(reason, "pre-PR safety review")

    def test_heartbeat(self):
        trig, _ = adversary.shouldTrigger("", config.ADVERSARY_HEARTBEAT_EVERY)
        self.assertTrue(trig)

    def test_no_trigger(self):
        trig, reason = adversary.shouldTrigger("clean work", subtask_position=1, attempt_count=1)
        self.assertFalse(trig)
        self.assertEqual(reason, "")


class TestReview(unittest.TestCase):
    def test_approved_via_brain(self):
        chat = _fakeChat({"verdict": "approved", "concerns": [], "notes": "looks complete"})
        rv = adversary.review("do x", "heartbeat", "output", ollama_chat=chat, goal="g")
        self.assertEqual(rv["verdict"], "approved")
        self.assertFalse(rv["stub"])
        self.assertEqual(rv["concerns"], [])

    def test_challenged_via_brain(self):
        chat = _fakeChat({"verdict": "rejected", "concerns": ["left a TODO", "no test"],
                          "notes": "incomplete"})
        rv = adversary.review("do x", "3 attempts", "output", ollama_chat=chat)
        self.assertEqual(rv["verdict"], "challenged")   # normalized from "rejected"
        self.assertEqual(len(rv["concerns"]), 2)
        self.assertFalse(rv["stub"])

    def test_stub_when_no_brain(self):
        rv = adversary.review("do x", "heartbeat", "output")
        self.assertEqual(rv["verdict"], "approved")
        self.assertTrue(rv["stub"])

    def test_fallback_on_bad_payload(self):
        def chat(system, user, *, want_json=False):
            return {"message": {"content": "not json at all"}}
        rv = adversary.review("do x", "heartbeat", "output", ollama_chat=chat)
        self.assertEqual(rv["verdict"], "approved")
        self.assertTrue(rv["stub"])

    def test_fallback_on_none_response(self):
        def chat(system, user, *, want_json=False):
            return None
        rv = adversary.review("do x", "heartbeat", "output", ollama_chat=chat)
        self.assertTrue(rv["stub"])

    def test_concerns_clamped_and_stringified(self):
        chat = _fakeChat({"verdict": "challenged",
                          "concerns": [f"c{i}" for i in range(20)] + ["", "  "]})
        rv = adversary.review("do x", "heartbeat", "output", ollama_chat=chat)
        self.assertLessEqual(len(rv["concerns"]), 10)
        self.assertTrue(all(c.strip() for c in rv["concerns"]))


if __name__ == "__main__":
    unittest.main()
