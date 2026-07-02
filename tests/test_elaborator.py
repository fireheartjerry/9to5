"""Tests for resilient elaboration (the run must not die at the starting line).

R5: the elaborator is a pure prompt builder over the ONE llm_io seam -- the memoized
client, retry/backoff, and extraction live in llm_io. These tests drive the seam by
patching ``llm_io.getClient`` (the blessed client factory)."""
import unittest
from unittest import mock

import llm_io
from agents import elaborator


def _client(chat):
    return mock.Mock(chat=chat)


class TestElaborate(unittest.TestCase):
    def test_success_returns_content(self):
        chat = mock.Mock(return_value={"message": {"content": "  the spec  "}})
        with mock.patch.object(llm_io, "getClient", return_value=_client(chat)):
            self.assertEqual(elaborator.elaborate("do a thing"), "the spec")

    def test_falls_back_when_ollama_down(self):
        chat = mock.Mock(side_effect=ConnectionError("refused"))
        with mock.patch.object(llm_io, "getClient", return_value=_client(chat)), \
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

        with mock.patch.object(llm_io, "getClient", return_value=_client(flaky)), \
             mock.patch("time.sleep"):
            self.assertEqual(elaborator.elaborate("g"), "recovered spec")
        self.assertEqual(calls["n"], 2)

    def test_injected_chat_seam_is_used(self):
        seen = {}

        def injected(system, user, *, act, want_json=False):
            seen["act"] = act
            return {"message": {"content": "seamed spec"}}

        self.assertEqual(elaborator.elaborate("g", chat=injected), "seamed spec")
        self.assertEqual(seen["act"], "elaborate")


class TestUniverse(unittest.TestCase):
    def test_defaults_when_brain_unavailable(self):
        chat = mock.Mock(side_effect=RuntimeError("down"))
        with mock.patch.object(llm_io, "getClient", return_value=_client(chat)), \
             mock.patch("time.sleep"):
            u = elaborator.extractUniverse("g", "spec", "/work/dir")
        self.assertEqual(u["allowed_paths"], ["/work/dir"])
        # Baseline hard boundaries always enforced.
        for d in __import__("config").UNIVERSE_DEFAULT_HARD_BOUNDARIES:
            self.assertIn(d, u["hard_boundaries"])

    def test_parses_brain_json(self):
        payload = '{"description":"d","allowed_paths":["a.py"],"allowed_to_expand_to":[],"hard_boundaries":["secret"]}'
        chat = mock.Mock(return_value={"message": {"content": payload}})
        with mock.patch.object(llm_io, "getClient", return_value=_client(chat)):
            u = elaborator.extractUniverse("g", "spec", "/w")
        self.assertEqual(u["allowed_paths"], ["a.py"])
        self.assertIn("secret", u["hard_boundaries"])

    def test_parses_pydantic_style_response(self):
        class _Msg:
            content = '{"description":"d","allowed_paths":["b.py"]}'

        class _Resp:
            message = _Msg()

        chat = mock.Mock(return_value=_Resp())
        with mock.patch.object(llm_io, "getClient", return_value=_client(chat)):
            u = elaborator.extractUniverse("g", "spec", "/w")
        self.assertEqual(u["allowed_paths"], ["b.py"])
