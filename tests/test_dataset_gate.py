"""Unit tests for the SIE data-quality & safety gate (learning/dataset.py)."""
import unittest
from unittest import mock

import config
from learning import dataset


class TestSecrets(unittest.TestCase):
    def test_detects_and_scrubs_common_secrets(self):
        samples = [
            "key sk-abcdef0123456789ABCDEF here",
            "token ghp_abcdefghijklmnopqrstuvwxyz0123",
            "aws AKIAIOSFODNN7EXAMPLE end",
            "api_key = supersecretvalue",
            "Authorization: Bearer abcdef123456ghijkl",
        ]
        for s in samples:
            self.assertTrue(dataset.has_secret(s), s)
            self.assertIn("<REDACTED>", dataset.scrub(s), s)
            self.assertFalse(dataset.has_secret(dataset.scrub(s)), s)  # idempotent

    def test_clean_text_untouched(self):
        s = "just author the invocation spec for the subtask"
        self.assertFalse(dataset.has_secret(s))
        self.assertEqual(dataset.scrub(s), s)


class TestGate(unittest.TestCase):
    def test_validate(self):
        self.assertTrue(dataset.validate({"prompt": "p", "completion": "c"}))
        self.assertFalse(dataset.validate({"prompt": "", "completion": "c"}))
        self.assertFalse(dataset.validate({"prompt": "p"}))

    def test_decontamination_drops_eval_suite(self):
        suite = [{"goal": "Fix the config bool parser"}]
        ex = {"prompt": "do x", "completion": "y", "goal": "fix the config bool parser"}
        out = dataset.clean([ex], suite=suite)
        self.assertEqual(out["stats"]["dropped_contaminated"], 1)
        self.assertEqual(out["examples"], [])

    def test_scrub_then_dedup(self):
        # Two examples differing only by the secret collapse to one after scrub.
        a = {"prompt": "use key sk-abcdefghij0123456789", "completion": "spec", "goal": "g"}
        b = {"prompt": "use key sk-zzzzzzzzzz9876543210", "completion": "spec", "goal": "g"}
        out = dataset.clean([a, b], suite=[])
        self.assertEqual(out["stats"]["scrubbed"], 2)
        self.assertEqual(out["stats"]["dropped_dup"], 1)
        self.assertEqual(len(out["examples"]), 1)

    def test_full_pipeline_counts(self):
        out = dataset.clean([
            {"prompt": "p1", "completion": "c1", "goal": "g1"},
            {"prompt": "", "completion": "c2"},                       # invalid
            {"prompt": "p1", "completion": "c1", "goal": "g1"},       # dup
        ], suite=[])
        s = out["stats"]
        self.assertEqual((s["in"], s["dropped_invalid"], s["dropped_dup"], s["out"]),
                         (3, 1, 1, 1))
