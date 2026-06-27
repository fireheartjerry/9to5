"""SIE routing safety: (1) active_brain_tag must never return a champion tag Ollama can't serve
(a dead tag bricks every brain call); (2) consider_promotion requires a STRICT improvement so an
empty/constant-fitness suite can't churn the champion on ties."""
import unittest
from unittest import mock

import config
from learning import finetune


class TestActiveBrainTagLiveness(unittest.TestCase):
    def setUp(self):
        finetune._SERVABLE_CACHE.update({"at": 0.0, "tags": None})

    def test_dead_champion_falls_back_to_base(self):
        with mock.patch.object(finetune.experience, "get_champion_adapter",
                               return_value={"tag": "9to5-brain:v9"}), \
                mock.patch.object(finetune, "_servable_tags", return_value={config.OLLAMA_MODEL}):
            self.assertEqual(finetune.active_brain_tag("all"), config.OLLAMA_MODEL)

    def test_live_champion_is_used(self):
        with mock.patch.object(finetune.experience, "get_champion_adapter",
                               return_value={"tag": "9to5-brain:v9"}), \
                mock.patch.object(finetune, "_servable_tags",
                                  return_value={"9to5-brain:v9", config.OLLAMA_MODEL}):
            self.assertEqual(finetune.active_brain_tag("all"), "9to5-brain:v9")

    def test_ollama_unreachable_falls_back_to_base(self):
        with mock.patch.object(finetune.experience, "get_champion_adapter",
                               return_value={"tag": "9to5-brain:v9"}), \
                mock.patch.object(finetune, "_servable_tags", return_value=None):
            self.assertEqual(finetune.active_brain_tag("all"), config.OLLAMA_MODEL)


class TestStrictPromotion(unittest.TestCase):
    def test_tie_does_not_promote(self):
        with mock.patch.object(finetune.experience, "promote_adapter") as prom:
            r = finetune.consider_promotion(1, challenger_fitness=0.5, champion_fitness=0.5)
            self.assertEqual(r["decision"], "reject")
            prom.assert_not_called()

    def test_strict_improvement_promotes(self):
        with mock.patch.object(finetune.experience, "promote_adapter") as prom:
            r = finetune.consider_promotion(1, challenger_fitness=0.6, champion_fitness=0.5)
            self.assertEqual(r["decision"], "promote")
            prom.assert_called_once()

    def test_regression_rejected(self):
        with mock.patch.object(finetune.experience, "promote_adapter") as prom:
            r = finetune.consider_promotion(1, challenger_fitness=0.4, champion_fitness=0.5)
            self.assertEqual(r["decision"], "reject")
            prom.assert_not_called()


if __name__ == "__main__":
    unittest.main()
