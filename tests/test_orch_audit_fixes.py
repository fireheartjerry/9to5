"""Gnarly-audit orchestrator fixes:
- _detectSelfReferential must NOT flag an external repo just because the goal mentions the bare
  product name '9to5' (that wrongly applies self-ref branching + core-file protection to the target).
- _adversaryReview must disable a persistently SOFT-failing GPT session (falls back to Ollama/stub
  with no hard session_dead) after a few consecutive misses, not re-pay GPT every review forever."""
import unittest
from unittest import mock

import config
from orchestrator import Orchestrator


def _orch():
    return Orchestrator(brain=mock.Mock(), obs=mock.Mock())


class TestDetectSelfReferential(unittest.TestCase):
    def _state(self, goal):
        s = mock.Mock()
        s.meta = {"goal_raw": goal, "goal_elaborated": ""}
        return s

    def test_bare_9to5_in_goal_is_not_selfref(self):
        orch = _orch()
        self.assertFalse(orch._detectSelfReferential(
            self._state("clone the 9to5 app for a client"), r"C:\some\external\repo"))

    def test_intent_phrase_in_external_repo_is_not_selfref(self):
        orch = _orch()
        self.assertFalse(orch._detectSelfReferential(
            self._state("improve its own code"), r"C:\external\repo"))

    def test_running_in_install_tree_is_selfref(self):
        orch = _orch()
        self.assertTrue(orch._detectSelfReferential(
            self._state("do some unrelated thing"), str(config.PROJECT_ROOT)))


class TestGptSoftFailDisable(unittest.TestCase):
    def test_disabled_after_consecutive_soft_fails(self):
        orch = _orch()
        orch._gemini_session_ok = True
        orch._gemini_ask = lambda m: "x"
        soft = {"tier": "ollama", "verdict": "approved", "concerns": []}
        with mock.patch("agents.second_brain.consult", return_value=soft), \
                mock.patch("platform_core.orchestration.review_mixin.discord"), \
                mock.patch("learning.adversary_trust.record"), \
                mock.patch.object(orch, "_worthGptReview", return_value=True):
            for _ in range(2):
                orch._adversaryReview("t", "r", "out", worth=True)
            self.assertTrue(orch._gemini_session_ok)   # still on after 2
            orch._adversaryReview("t", "r", "out", worth=True)
            self.assertFalse(orch._gemini_session_ok)  # disabled after the 3rd soft-fail

    def test_real_gpt_verdict_resets_streak(self):
        orch = _orch()
        orch._gemini_session_ok = True
        orch._gemini_ask = lambda m: "x"
        with mock.patch("platform_core.orchestration.review_mixin.discord"), \
                mock.patch("learning.adversary_trust.record"), \
                mock.patch.object(orch, "_worthGptReview", return_value=True):
            with mock.patch("agents.second_brain.consult",
                            return_value={"tier": "ollama", "verdict": "approved"}):
                orch._adversaryReview("t", "r", "o", worth=True)
                orch._adversaryReview("t", "r", "o", worth=True)
            with mock.patch("agents.second_brain.consult",
                            return_value={"tier": "gpt", "verdict": "approved"}):
                orch._adversaryReview("t", "r", "o", worth=True)   # real GPT -> reset
            with mock.patch("agents.second_brain.consult",
                            return_value={"tier": "ollama", "verdict": "approved"}):
                orch._adversaryReview("t", "r", "o", worth=True)
        self.assertTrue(orch._gemini_session_ok)   # streak reset, only 1 soft-fail since


if __name__ == "__main__":
    unittest.main()
