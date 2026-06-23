"""Tests for resilient elaboration (the run must not die at the starting line)."""
import unittest
from unittest import mock

from agents import elaborator


class TestElaborate(unittest.TestCase):
    def test_success_returns_content(self):
        with mock.patch.object(elaborator._OLLAMA, "chat",
                               return_value={"message": {"content": "  the spec  "}}):
            self.assertEqual(elaborator.elaborate("do a thing"), "the spec")

    def test_falls_back_when_ollama_down(self):
        with mock.patch.object(elaborator._OLLAMA, "chat",
                               side_effect=ConnectionError("refused")), \
             mock.patch("time.sleep"):
            spec = elaborator.elaborate("fix the bug in foo.py")
        self.assertIn("Objective", spec)
        self.assertIn("fix the bug in foo.py", spec)   # raw goal preserved

    def test_retries_then_succeeds(self):
        calls = {"n": 0}

        def flaky(*a, **k):
            calls["n"] += 1
            if calls["n"] < 2:
                raise TimeoutError("slow")
            return {"message": {"content": "recovered spec"}}

        with mock.patch.object(elaborator._OLLAMA, "chat", side_effect=flaky), \
             mock.patch("time.sleep"):
            self.assertEqual(elaborator.elaborate("g"), "recovered spec")
        self.assertEqual(calls["n"], 2)


class TestUniverse(unittest.TestCase):
    def test_defaults_when_brain_unavailable(self):
        with mock.patch.object(elaborator._OLLAMA, "chat",
                               side_effect=RuntimeError("down")), \
             mock.patch("time.sleep"):
            u = elaborator.extractUniverse("g", "spec", "/work/dir")
        self.assertEqual(u["allowed_paths"], ["/work/dir"])
        # Baseline hard boundaries always enforced.
        for d in __import__("config").UNIVERSE_DEFAULT_HARD_BOUNDARIES:
            self.assertIn(d, u["hard_boundaries"])

    def test_parses_brain_json(self):
        payload = '{"description":"d","allowed_paths":["a.py"],"allowed_to_expand_to":[],"hard_boundaries":["secret"]}'
        with mock.patch.object(elaborator._OLLAMA, "chat",
                               return_value={"message": {"content": payload}}):
            u = elaborator.extractUniverse("g", "spec", "/w")
        self.assertEqual(u["allowed_paths"], ["a.py"])
        self.assertIn("secret", u["hard_boundaries"])


if __name__ == "__main__":
    unittest.main()
