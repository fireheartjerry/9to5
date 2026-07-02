"""The Adversary must FAIL CLOSED on a malformed/missing verdict: a real 'challenged' the model
expressed off-contract (typo, missing key, prose) must degrade to the conservative *labeled* stub,
never a silent clean 'approved' that neuters the PR-hold and remediation (FX-5)."""
import unittest
from unittest import mock

from agents import adversary as adv


class TestNormalizeVerdict(unittest.TestCase):
    def test_recognized_values(self):
        self.assertEqual(adv._normalizeVerdict("approved"), adv._APPROVED)
        self.assertEqual(adv._normalizeVerdict("CHALLENGED"), adv._CHALLENGED)
        self.assertEqual(adv._normalizeVerdict("pass"), adv._APPROVED)
        self.assertEqual(adv._normalizeVerdict("rejected"), adv._CHALLENGED)

    def test_absent_or_offcontract_is_none(self):
        self.assertIsNone(adv._normalizeVerdict(None))          # missing key
        self.assertIsNone(adv._normalizeVerdict(""))            # empty
        self.assertIsNone(adv._normalizeVerdict("looks fine to me"))   # prose
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
            return adv.review("subtask", "heartbeat", "executor output",
                              ollama_chat=lambda *a, **k: object(), goal="goal")

    def test_missing_verdict_becomes_labeled_challenge(self):
        r = self._review('{"concerns": ["real issue"]}')   # NO verdict key
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
        '{"verdict": "rejected", "concerns": ["x"]}',      # normalized to challenged
        '```json\n{"verdict": "challenged"}\n```',          # fenced
        'prose {"verdict": "approved"} trailing {braces}',  # balanced-walker salvage
        '{"concerns": ["no verdict key"]}',                 # off-contract -> challenged
        'not json at all',                                  # garbled -> challenged
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
            self.assertEqual(a["verdict"], b["verdict"],
                             f"paths diverged on {payload!r}: {a['verdict']} vs {b['verdict']}")

    def test_garbled_is_challenged_on_both_paths(self):
        for payload in ('not json at all', '{"concerns": ["no verdict"]}'):
            self.assertEqual(self._via_ollama(payload)["verdict"], adv._CHALLENGED)
            self.assertEqual(self._via_browser(payload)["verdict"], adv._CHALLENGED)
