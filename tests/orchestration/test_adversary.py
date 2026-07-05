"""Unit tests for the Adversary reviewer (trigger logic + Ollama-backed critique).

The Adversary must FAIL CLOSED on a malformed/missing verdict: a real 'challenged' the model
expressed off-contract (typo, missing key, prose) must degrade to the conservative *labeled* stub,
never a silent clean 'approved' that neuters the PR-hold and remediation (FX-5)."""

import json
import unittest
from unittest import mock

import config
from agents import adversary
from agents import adversary as adv


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
        chat = _fakeChat(
            {"verdict": "rejected", "concerns": ["left a TODO", "no test"], "notes": "incomplete"}
        )
        rv = adversary.review("do x", "3 attempts", "output", ollama_chat=chat)
        self.assertEqual(rv["verdict"], "challenged")  # normalized from "rejected"
        self.assertEqual(len(rv["concerns"]), 2)
        self.assertFalse(rv["stub"])

    def test_stub_when_no_brain(self):
        rv = adversary.review("do x", "heartbeat", "output")
        # Honest label: a brain that could NOT review is 'unreviewed', never a silent 'approved'.
        self.assertEqual(rv["verdict"], "unreviewed")
        self.assertTrue(rv["stub"])

    def test_unavailable_stub_is_unreviewed_and_does_not_hard_block(self):
        """FX (surface, don't stall): when NO brain can produce a verdict, the result must be the
        honest 'unreviewed' (never a false 'approved' that reads as a real pass), and it must NOT
        hard-block the run -- is_blocking stays False so a dead LLM never stalls all work."""
        from agents import second_brain

        rv = adversary.review("do x", "heartbeat", "output")  # no ollama_chat -> unavailable -> stub
        self.assertTrue(rv["stub"])
        self.assertEqual(rv["verdict"], "unreviewed")
        self.assertFalse(second_brain.is_blocking(rv))

    def test_garbled_payload_fails_closed_as_challenged(self):
        # R10: the brain RESPONDED but the verdict is unparseable -> CHALLENGED (labeled),
        # never a silent clean approve that would neuter the PR-hold/remediation.
        def chat(system, user, *, want_json=False):
            return {"message": {"content": "not json at all"}}

        rv = adversary.review("do x", "heartbeat", "output", ollama_chat=chat)
        self.assertEqual(rv["verdict"], "challenged")
        self.assertTrue(rv["stub"])

    def test_fallback_on_none_response(self):
        def chat(system, user, *, want_json=False):
            return None

        rv = adversary.review("do x", "heartbeat", "output", ollama_chat=chat)
        self.assertTrue(rv["stub"])

    def test_concerns_clamped_and_stringified(self):
        chat = _fakeChat({"verdict": "challenged", "concerns": [f"c{i}" for i in range(20)] + ["", "  "]})
        rv = adversary.review("do x", "heartbeat", "output", ollama_chat=chat)
        self.assertLessEqual(len(rv["concerns"]), 10)
        self.assertTrue(all(c.strip() for c in rv["concerns"]))


class TestReviewViaBrowser(unittest.TestCase):
    """Phase-2 routing: Adversary -> Gemini via the google-genai SDK second-brain shim."""

    def _ask(self, payload):
        """A browser_ask stand-in returning ``payload`` JSON as the Gemini reply."""
        return lambda message: json.dumps(payload)

    def test_approved_via_browser(self):
        ask = self._ask({"verdict": "approved", "concerns": [], "notes": "complete"})
        rv = adversary.reviewViaBrowser("do x", "pre-PR safety review", "output", browser_ask=ask, goal="g")
        self.assertEqual(rv["verdict"], "approved")
        self.assertFalse(rv["stub"])
        self.assertEqual(rv["surface"], "gemini")
        self.assertEqual(rv["trigger_reason"], "pre-PR safety review")

    def test_challenged_via_browser_normalizes(self):
        ask = self._ask({"verdict": "reject", "concerns": ["faked verify", "left TODO"]})
        rv = adversary.reviewViaBrowser("do x", "heartbeat", "output", browser_ask=ask)
        self.assertEqual(rv["verdict"], "challenged")  # normalized from "reject"
        self.assertEqual(len(rv["concerns"]), 2)
        self.assertFalse(rv["stub"])

    def test_concerns_clamped_via_browser(self):
        ask = self._ask({"verdict": "challenged", "concerns": [f"c{i}" for i in range(20)] + ["", "   "]})
        rv = adversary.reviewViaBrowser("do x", "heartbeat", "output", browser_ask=ask)
        self.assertLessEqual(len(rv["concerns"]), 10)
        self.assertTrue(all(c.strip() for c in rv["concerns"]))

    def test_stub_when_browser_unavailable(self):
        rv = adversary.reviewViaBrowser("do x", "heartbeat", "output", browser_ask=lambda message: None)
        self.assertEqual(rv["verdict"], "unreviewed")  # unavailable brain -> honest unreviewed
        self.assertTrue(rv["stub"])

    def test_garbled_reply_fails_closed_as_challenged(self):
        # R10: same fail-closed contract as the Ollama path, via the ONE _parseVerdict.
        rv = adversary.reviewViaBrowser(
            "do x", "heartbeat", "output", browser_ask=lambda message: "not json at all"
        )
        self.assertEqual(rv["verdict"], "challenged")
        self.assertTrue(rv["stub"])

    def test_stub_when_browser_ask_raises(self):
        def boom(message):
            raise RuntimeError("CDP socket closed")

        rv = adversary.reviewViaBrowser("do x", "heartbeat", "output", browser_ask=boom)
        self.assertTrue(rv["stub"])

    def test_prompt_carries_system_and_output(self):
        seen = {}

        def ask(message):
            seen["message"] = message
            return json.dumps({"verdict": "approved", "concerns": []})

        adversary.reviewViaBrowser(
            "build parser", "heartbeat", "UNIQUE_EXECUTOR_MARKER", browser_ask=ask, goal="ship it"
        )
        self.assertIn("9TO5 Adversary", seen["message"])  # system prompt is included
        self.assertIn("UNIQUE_EXECUTOR_MARKER", seen["message"])
        self.assertIn("build parser", seen["message"])

    def test_default_browser_ask_is_browser_executor(self):
        """With no injected callable it must route through the real Gemini helper (patched)."""
        from agents import browser_executor

        with mock.patch.object(
            browser_executor, "askGemini", return_value=json.dumps({"verdict": "approved", "concerns": []})
        ) as m:
            rv = adversary.reviewViaBrowser("do x", "heartbeat", "output")
        m.assert_called_once()
        self.assertEqual(rv["verdict"], "approved")
        self.assertFalse(rv["stub"])


class TestNormalizeVerdict(unittest.TestCase):
    def test_recognized_values(self):
        self.assertEqual(adv._normalizeVerdict("approved"), adv._APPROVED)
        self.assertEqual(adv._normalizeVerdict("CHALLENGED"), adv._CHALLENGED)
        self.assertEqual(adv._normalizeVerdict("pass"), adv._APPROVED)
        self.assertEqual(adv._normalizeVerdict("rejected"), adv._CHALLENGED)

    def test_absent_or_offcontract_is_none(self):
        self.assertIsNone(adv._normalizeVerdict(None))  # missing key
        self.assertIsNone(adv._normalizeVerdict(""))  # empty
        self.assertIsNone(adv._normalizeVerdict("looks fine to me"))  # prose
        self.assertIsNone(adv._normalizeVerdict("challanged"))  # typo'd challenge -> NOT approved

    def test_concern_word_challenges(self):
        self.assertEqual(adv._normalizeVerdict("approved with a concern"), adv._CHALLENGED)


class TestLoadJsonLooseBalanced(unittest.TestCase):
    def test_recovers_verdict_despite_trailing_braces(self):
        """A real 'challenged' verdict followed by trailing prose that contains braces must still be
        recovered. The old greedy r'{.*}' spanned first-'{' to last-'}' (verdict + the trailing
        braces) -> json.loads failed -> the challenge was lost to a stub-approve. The balanced walker
        closes at the verdict object's depth-0 '}'."""
        text = '{"verdict": "challenged", "concerns": ["real bug"]}\n\nNote: see {the diff} for details.'
        out = adv._loadJsonLoose(text)
        self.assertIsInstance(out, dict)
        self.assertEqual(out.get("verdict"), "challenged")

    def test_plain_object_with_leading_prose(self):
        out = adv._loadJsonLoose('Here is my review: {"verdict": "approved", "concerns": []}')
        self.assertEqual(out.get("verdict"), "approved")


class TestParseVerdictFailsClosed(unittest.TestCase):
    def test_missing_verdict_raises(self):
        with self.assertRaises(ValueError):
            adv._parseVerdict('{"concerns": ["x"]}', "reason", surface="browser")

    def test_offcontract_verdict_raises(self):
        with self.assertRaises(ValueError):
            adv._parseVerdict('{"verdict": "meh"}', "reason", surface="browser")

    def test_valid_verdict_parses(self):
        out = adv._parseVerdict('{"verdict": "challenged", "concerns": ["bug"]}', "reason", surface="browser")
        self.assertEqual(out["verdict"], adv._CHALLENGED)
        self.assertFalse(out["stub"])


class TestReviewFailsClosedToStub(unittest.TestCase):
    def _review(self, payload_json):
        with mock.patch.object(adv.llm_io, "responseText", return_value=payload_json):
            return adv.review(
                "subtask", "heartbeat", "executor output", ollama_chat=lambda *a, **k: object(), goal="goal"
            )

    def test_missing_verdict_becomes_labeled_challenge(self):
        r = self._review('{"concerns": ["real issue"]}')  # NO verdict key
        self.assertTrue(r["stub"], "malformed verdict was silently treated as a clean approve")
        self.assertEqual(r["verdict"], adv._CHALLENGED, "garbled must fail closed (R10)")

    def test_valid_challenge_is_not_stub(self):
        r = self._review('{"verdict": "challenged", "concerns": ["x"]}')
        self.assertEqual(r["verdict"], adv._CHALLENGED)
        self.assertFalse(r["stub"])


class TestOneParserBothSurfaces(unittest.TestCase):
    """R10 property test over the two previously-diverging paths: review() (which used to
    inline a byte-for-byte copy of _parseVerdict) and reviewViaBrowser() must agree on
    every payload -- same verdict, same fail-closed handling of garbled output."""

    PAYLOADS = [
        '{"verdict": "approved", "concerns": []}',
        '{"verdict": "challenged", "concerns": ["bug"], "severity": "high"}',
        '{"verdict": "rejected", "concerns": ["x"]}',  # normalized to challenged
        '```json\n{"verdict": "challenged"}\n```',  # fenced
        'prose {"verdict": "approved"} trailing {braces}',  # balanced-walker salvage
        '{"concerns": ["no verdict key"]}',  # off-contract -> challenged
        "not json at all",  # garbled -> challenged
    ]

    def _via_ollama(self, payload):
        with mock.patch.object(adv.llm_io, "responseText", return_value=payload):
            return adv.review("s", "r", "o", ollama_chat=lambda *a, **k: object())

    def _via_browser(self, payload):
        return adv.reviewViaBrowser("s", "r", "o", browser_ask=lambda message: payload)

    def test_both_paths_agree_on_every_payload(self):
        for payload in self.PAYLOADS:
            a = self._via_ollama(payload)
            b = self._via_browser(payload)
            self.assertEqual(
                a["verdict"], b["verdict"], f"paths diverged on {payload!r}: {a['verdict']} vs {b['verdict']}"
            )

    def test_garbled_is_challenged_on_both_paths(self):
        for payload in ("not json at all", '{"concerns": ["no verdict"]}'):
            self.assertEqual(self._via_ollama(payload)["verdict"], adv._CHALLENGED)
            self.assertEqual(self._via_browser(payload)["verdict"], adv._CHALLENGED)
