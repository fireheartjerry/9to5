"""Orchestration tool enhancements: finer-grained control.

Covers:
- llm_io._firstBalancedObject / responseJson: balanced-brace salvage fix for greedy {.*} regex
- adversary.shouldTrigger: all four trigger conditions
- adversary.review: stub path (no brain), rich-field defaults
- adversary._loadJsonLoose: fence, prose, dict pass-through
- adversary.systemFor: review-type guidance injection
- vlm_healer._loadJson: all input shapes
- vlm_healer.heal: clean degradation when ollama unavailable
"""
import pathlib
import sys
import types
import unittest

# Allow `python tests/test_tools.py` from any working directory.
_ROOT = pathlib.Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

import llm_io
from agents import adversary
from agents import vlm_healer


# ---------------------------------------------------------------------------
# llm_io helpers
# ---------------------------------------------------------------------------

class TestFirstBalancedObject(unittest.TestCase):

    def test_simple_object(self):
        self.assertEqual(llm_io._firstBalancedObject('{"a": 1}'), '{"a": 1}')

    def test_nested_object(self):
        s = '{"a": {"b": 2}}'
        self.assertEqual(llm_io._firstBalancedObject(s), s)

    def test_stops_at_first_object_not_last(self):
        s = 'prefix {"x": 1} prose {"y": 2} suffix'
        self.assertEqual(llm_io._firstBalancedObject(s), '{"x": 1}')

    def test_string_containing_braces_not_counted(self):
        # The } inside the string value must not close the outer object early.
        s = '{"key": "val}ue"}'
        self.assertEqual(llm_io._firstBalancedObject(s), s)

    def test_no_object_returns_none(self):
        self.assertIsNone(llm_io._firstBalancedObject("no braces here"))

    def test_unclosed_returns_none(self):
        self.assertIsNone(llm_io._firstBalancedObject('{"unclosed": 1'))

    def test_escaped_quote_inside_string(self):
        s = '{"k": "a\\"}"}'     # value is: a"}  -- the first } is escaped inside string
        result = llm_io._firstBalancedObject(s)
        self.assertIsNotNone(result)
        import json
        self.assertEqual(json.loads(result), {"k": 'a"}'})


class TestResponseJson(unittest.TestCase):

    def _resp(self, text):
        return {"message": {"content": text}}

    def test_clean_json(self):
        self.assertEqual(llm_io.responseJson(self._resp('{"ok": 1}')), {"ok": 1})

    def test_fenced_json(self):
        self.assertEqual(llm_io.responseJson(self._resp('```json\n{"a": 2}\n```')), {"a": 2})

    def test_prose_around_json(self):
        r = llm_io.responseJson(self._resp('Sure! Here: {"verdict": "approved"} done.'))
        self.assertEqual(r, {"verdict": "approved"})

    def test_two_objects_returns_first(self):
        # Greedy regex bug: this would have matched {"a":1} ... {"b":2} as one blob.
        r = llm_io.responseJson(self._resp('{"a": 1} extra text {"b": 2}'))
        self.assertEqual(r, {"a": 1})

    def test_nested_json_parsed_correctly(self):
        r = llm_io.responseJson(self._resp('{"outer": {"inner": 42}}'))
        self.assertEqual(r, {"outer": {"inner": 42}})

    def test_none_resp_returns_none(self):
        self.assertIsNone(llm_io.responseJson(None))

    def test_empty_content_returns_none(self):
        self.assertIsNone(llm_io.responseJson(self._resp("")))

    def test_invalid_json_returns_none(self):
        self.assertIsNone(llm_io.responseJson(self._resp("not json at all")))


# ---------------------------------------------------------------------------
# adversary helpers
# ---------------------------------------------------------------------------

class TestShouldTrigger(unittest.TestCase):

    def test_uncertainty_phrase(self):
        triggered, reason = adversary.shouldTrigger("I'm not sure about this", 0)
        self.assertTrue(triggered)
        self.assertIn("uncertainty", reason)

    def test_max_attempts(self):
        import config
        triggered, reason = adversary.shouldTrigger("ok", 0,
                                                    attempt_count=config.MAX_SUBTASK_ATTEMPTS)
        self.assertTrue(triggered)
        self.assertIn("attempts", reason)

    def test_pre_pr(self):
        triggered, reason = adversary.shouldTrigger("ok", 0, pre_pr=True)
        self.assertTrue(triggered)
        self.assertIn("pre-PR", reason)

    def test_heartbeat(self):
        import config
        n = config.ADVERSARY_HEARTBEAT_EVERY
        triggered, reason = adversary.shouldTrigger("ok", n)
        self.assertTrue(triggered)
        self.assertIn("heartbeat", reason)

    def test_no_trigger(self):
        triggered, _ = adversary.shouldTrigger("everything looks fine", 1)
        self.assertFalse(triggered)


class TestReviewStub(unittest.TestCase):

    def test_no_brain_returns_approved_stub(self):
        rv = adversary.review("do thing", "test", "output here", ollama_chat=None)
        self.assertEqual(rv["verdict"], "approved")
        self.assertTrue(rv.get("stub"))
        self.assertIsNone(rv.get("confidence"))

    def test_brain_error_returns_approved_stub(self):
        def bad_chat(system, user, **kw):
            raise RuntimeError("brain exploded")
        rv = adversary.review("do thing", "test", "output", ollama_chat=bad_chat)
        self.assertEqual(rv["verdict"], "approved")
        self.assertTrue(rv.get("stub"))

    def test_brain_returns_junk_is_stub(self):
        def junk_chat(system, user, **kw):
            return {"message": {"content": "not json"}}
        rv = adversary.review("do thing", "test", "output", ollama_chat=junk_chat)
        self.assertEqual(rv["verdict"], "approved")
        self.assertTrue(rv.get("stub"))


class TestLoadJsonLoose(unittest.TestCase):

    def test_plain_json_string(self):
        self.assertEqual(adversary._loadJsonLoose('{"verdict": "approved"}'),
                         {"verdict": "approved"})

    def test_fenced_json(self):
        self.assertEqual(adversary._loadJsonLoose('```json\n{"verdict": "challenged"}\n```'),
                         {"verdict": "challenged"})

    def test_prose_wrapped(self):
        result = adversary._loadJsonLoose('Here is my response: {"verdict": "approved"} end')
        self.assertEqual(result, {"verdict": "approved"})

    def test_dict_passthrough(self):
        d = {"verdict": "approved", "concerns": []}
        self.assertIs(adversary._loadJsonLoose(d), d)

    def test_none_returns_none(self):
        self.assertIsNone(adversary._loadJsonLoose(None))

    def test_empty_string_returns_none(self):
        self.assertIsNone(adversary._loadJsonLoose(""))

    def test_invalid_returns_none(self):
        self.assertIsNone(adversary._loadJsonLoose("not json at all "))


class TestSystemFor(unittest.TestCase):

    def test_subtask_default(self):
        s = adversary.systemFor("subtask")
        self.assertIn("subtask", s.lower())

    def test_plan_guidance_injected(self):
        s = adversary.systemFor("plan")
        self.assertIn("PLAN", s)

    def test_unknown_type_falls_back_to_subtask(self):
        s = adversary.systemFor("nonexistent_type")
        subtask_s = adversary.systemFor("subtask")
        self.assertEqual(s, subtask_s)


# ---------------------------------------------------------------------------
# vlm_healer helpers
# ---------------------------------------------------------------------------

class TestVlmHealerLoadJson(unittest.TestCase):

    def test_dict_passthrough(self):
        d = {"state": "ready"}
        self.assertIs(vlm_healer._loadJson(d), d)

    def test_plain_json(self):
        self.assertEqual(vlm_healer._loadJson('{"state": "login_wall"}'),
                         {"state": "login_wall"})

    def test_fenced(self):
        self.assertEqual(vlm_healer._loadJson('```json\n{"state": "modal"}\n```'),
                         {"state": "modal"})

    def test_prose(self):
        result = vlm_healer._loadJson('result: {"state": "ready"} end')
        self.assertEqual(result, {"state": "ready"})

    def test_none_returns_none(self):
        self.assertIsNone(vlm_healer._loadJson(None))

    def test_invalid_returns_none(self):
        self.assertIsNone(vlm_healer._loadJson("not json"))


class TestVlmHealDegrades(unittest.TestCase):
    """heal() must return {} cleanly when ollama is unavailable — never crash a run."""

    def _stub_no_ollama(self):
        """Temporarily hide the ollama package so the import inside heal() fails."""
        orig = sys.modules.get("ollama")
        sys.modules["ollama"] = None  # type: ignore[assignment]  -- ImportError on import
        return orig

    def _restore_ollama(self, orig):
        if orig is None:
            sys.modules.pop("ollama", None)
        else:
            sys.modules["ollama"] = orig

    def test_heal_returns_empty_when_ollama_missing(self):
        orig = self._stub_no_ollama()
        try:
            result = vlm_healer.heal(b"png", "<html/>", want="composer")
            self.assertEqual(result, {})
        finally:
            self._restore_ollama(orig)

    def test_heal_returns_empty_on_client_error(self):
        """Simulate a client that raises on chat() — must still degrade to {}."""
        class _BadClient:
            def chat(self, **kw):
                raise ConnectionError("ollama unreachable")

        fake_ollama = types.ModuleType("ollama")
        fake_ollama.Client = lambda **kw: _BadClient()  # type: ignore[attr-defined]
        orig = sys.modules.get("ollama")
        sys.modules["ollama"] = fake_ollama
        try:
            result = vlm_healer.heal(b"png", "<html/>", want="composer")
            self.assertEqual(result, {})
        finally:
            self._restore_ollama(orig)


if __name__ == "__main__":
    unittest.main()
