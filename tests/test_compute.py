"""Tests for the GPU compute router + GPU-routed training backends."""
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import config
from learning import compute, finetune


class TestComputeRouter(unittest.TestCase):
    def setUp(self):
        compute.reset_cache()

    def tearDown(self):
        mock.patch.stopall()
        compute.reset_cache()

    def test_off_disables_training(self):
        with mock.patch.object(config, "SIE_COMPUTE", "off"):
            self.assertFalse(compute.training_enabled())
            self.assertFalse(compute.should_use_gpu())

    def test_cpu_never_uses_gpu(self):
        with mock.patch.object(config, "SIE_COMPUTE", "cpu"):
            self.assertTrue(compute.training_enabled())
            self.assertFalse(compute.should_use_gpu())

    def test_auto_uses_gpu_only_when_present(self):
        with mock.patch.object(config, "SIE_COMPUTE", "auto"), \
             mock.patch.object(compute, "detect_gpu", return_value={"available": True, "name": "RTX"}):
            compute.reset_cache()
            self.assertTrue(compute.should_use_gpu())
            self.assertEqual(compute.device(), "cuda")
        compute.reset_cache()
        with mock.patch.object(config, "SIE_COMPUTE", "auto"), \
             mock.patch.object(compute, "detect_gpu", return_value={"available": False, "name": None}):
            self.assertFalse(compute.should_use_gpu())
            self.assertEqual(compute.device(), "cpu")

    def test_summary_shape(self):
        s = compute.summary()
        self.assertIn("policy", s)
        self.assertIn("will_train_on", s)


class TestTrainerRouting(unittest.TestCase):
    def tearDown(self):
        mock.patch.stopall()

    def test_default_trainer_none_without_gpu(self):
        # No GPU in this container -> default trainer is None -> cycle skips, never crashes.
        with mock.patch.object(finetune, "default_trainer", wraps=finetune.default_trainer):
            self.assertIsNone(finetune.default_trainer())
            self.assertIsNone(finetune.default_dpo_trainer())

    def test_trainer_resolves_when_gpu_and_policy_allow(self):
        # Router says GPU available -> default_trainer returns a callable (the real _train,
        # which would import torch only when invoked).
        with mock.patch("learning.compute.training_enabled", return_value=True), \
             mock.patch("learning.compute.should_use_gpu", return_value=True):
            self.assertIsNotNone(finetune.default_trainer())
            self.assertIsNotNone(finetune.default_dpo_trainer())


if __name__ == "__main__":
    unittest.main()
