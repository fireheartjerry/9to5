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

    def test_missing_verdict_becomes_labeled_stub(self):
        r = self._review('{"concerns": ["real issue"]}')   # NO verdict key
        self.assertTrue(r["stub"], "malformed verdict was silently treated as a clean approve")

    def test_valid_challenge_is_not_stub(self):
        r = self._review('{"verdict": "challenged", "concerns": ["x"]}')
        self.assertEqual(r["verdict"], adv._CHALLENGED)
        self.assertFalse(r["stub"])


if __name__ == "__main__":
    unittest.main()
