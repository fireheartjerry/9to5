"""Regression guard for the empty-completion ROOT CAUSE: the ollama-python client returns
pydantic ChatResponse/Message objects (NOT dicts), and the old isinstance(resp, dict) gate
threw away the content of every real reply -> "Brain (Ollama) unavailable; empty completion".

These objects support attribute access (resp.message.content), subscript, and .get(), but are
NOT dict instances. llm_io.responseText/responseJson (and orchestrator._chatText/_chatJson which
delegate to them) must extract from them while still returning ''/None for malformed shapes.
"""
import unittest
from unittest import mock

import llm_io
from orchestrator import _chatText, _chatJson


class _Msg:
    """Mimics ollama.Message: attribute access + .get(), NOT a dict."""
    def __init__(self, content):
        self.content = content

    def get(self, k, d=None):
        return getattr(self, k, d)


class _Resp:
    """Mimics ollama.ChatResponse: holds a pydantic Message, NOT a dict."""
    def __init__(self, content):
        self.message = _Msg(content)

    def get(self, k, d=None):
        return getattr(self, k, d)


class TestPydanticExtraction(unittest.TestCase):
    def test_extracts_from_non_dict_pydantic_response(self):
        r = _Resp('{"subtasks": []}')
        self.assertFalse(isinstance(r, dict))           # the exact condition that broke the old code
        self.assertEqual(llm_io.responseText(r), '{"subtasks": []}')
        self.assertEqual(_chatText(r), '{"subtasks": []}')   # orchestrator delegates to llm_io
        self.assertEqual(_chatJson(r), {"subtasks": []})

    def test_dict_response_still_works(self):
        r = {"message": {"content": '{"ok": 1}'}}
        self.assertEqual(_chatText(r), '{"ok": 1}')
        self.assertEqual(_chatJson(r), {"ok": 1})

    def test_malformed_shapes_return_empty(self):
        for bad in [None, {}, {"message": {}}, {"message": "x"}, {"message": {"content": None}},
                    {"message": {"content": 5}}, _Resp(None), _Resp(5), "str", 42]:
            self.assertEqual(_chatText(bad), "", f"{bad!r} should extract to ''")
            self.assertIsNone(_chatJson(bad), f"{bad!r} should parse to None")

    def test_fence_and_prose_salvage_on_pydantic(self):
        self.assertEqual(_chatJson(_Resp('```json\n{"a": 1}\n```')), {"a": 1})
        self.assertEqual(_chatJson(_Resp('sure, here: {"a": 2} done')), {"a": 2})


class TestParseJsonLooseGolden(unittest.TestCase):
    """Golden cases merged from the three pre-R5 implementations (brain_io.parseJsonText,
    llm_io.responseJson, adversary._loadJsonLoose) -- ONE ladder now owns them all."""

    def test_clean_json(self):
        self.assertEqual(llm_io.parseJsonLoose('{"x": 1}'), {"x": 1})

    def test_fenced_json(self):
        self.assertEqual(llm_io.parseJsonLoose('```json\n{"x": 1}\n```'), {"x": 1})

    def test_prose_wrapped_object(self):
        self.assertEqual(llm_io.parseJsonLoose('Here you go: {"x": 2} hope that helps'), {"x": 2})

    def test_prose_wrapped_array_preserves_the_complete_array(self):
        text = 'Here you go: [{"id": 1}, {"id": 2}] hope that helps'
        self.assertEqual(llm_io.parseJsonLoose(text), [{"id": 1}, {"id": 2}])

    def test_nested_mixed_containers_are_balanced_by_type(self):
        text = 'prefix [{"rows": [1, {"deep": True}]}] suffix'.replace("True", "true")
        self.assertEqual(llm_io.parseJsonLoose(text), [{"rows": [1, {"deep": True}]}])

    def test_json_scalars_are_not_structured_completion_success(self):
        for scalar in ('"text"', "17", "true", "null"):
            self.assertIsNone(llm_io.parseJsonLoose(scalar))

    def test_fenced_array_inside_prose_is_extracted(self):
        text = 'Result follows:\n```json\n[{"id": 1}]\n```\nDone.'
        self.assertEqual(llm_io.parseJsonLoose(text), [{"id": 1}])

    def test_markdown_brackets_do_not_preempt_a_later_json_object(self):
        text = 'See [the note] first, then use {"ok": 1}.'
        self.assertEqual(llm_io.parseJsonLoose(text), {"ok": 1})

    def test_markdown_brackets_alone_are_not_repaired_into_fabricated_json(self):
        self.assertIsNone(llm_io.parseJsonLoose("See [the note] for details."))

    def test_trailing_braces_use_balanced_walker(self):
        # the naive greedy r"{.*}" spans to the LAST '}' and fails; the balanced walker wins
        text = '{"verdict": "challenged"}\n\nNote: see {the diff} for details.'
        self.assertEqual(llm_io.parseJsonLoose(text), {"verdict": "challenged"})

    def test_truncated_object_repaired(self):
        out = llm_io.parseJsonLoose('{"subtasks": [{"title": "a"},], "n": 3')
        self.assertIsInstance(out, dict)
        self.assertEqual(out["n"], 3)

    def test_pure_prose_is_none(self):
        self.assertIsNone(llm_io.parseJsonLoose("no json here at all"))
        self.assertIsNone(llm_io.parseJsonLoose(""))
        self.assertIsNone(llm_io.parseJsonLoose(None))

    def test_delegates_are_the_one_ladder(self):
        from platform_core.orchestration import brain_io
        from agents import adversary_review
        text = '```json\n{"verdict": "approved"}\n```'
        self.assertEqual(brain_io.parseJsonText(text), llm_io.parseJsonLoose(text))
        self.assertEqual(adversary_review._loadJsonLoose(text), llm_io.parseJsonLoose(text))


class _ActAwareClient:
    """Sim-shaped client: explicit act kwarg + records calls."""
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def chat(self, *, model=None, messages=None, act=None, **kwargs):
        self.calls.append({"act": act, "kwargs": kwargs})
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


class _RealShapedClient:
    """ollama.Client-shaped: NO act parameter, NO **kwargs -- act must never reach it."""
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    def chat(self, model="", messages=None, *, tools=None, stream=False, format=None,
             options=None, keep_alive=None):
        self.calls += 1
        return self.reply


class TestBlessedChat(unittest.TestCase):
    def test_act_forwarded_to_act_aware_client(self):
        cli = _ActAwareClient([{"message": {"content": "ok"}}])
        resp = llm_io.chat("s", "u", act="plan", client=cli)
        self.assertEqual(llm_io.responseText(resp), "ok")
        self.assertEqual(cli.calls[0]["act"], "plan")

    def test_act_never_reaches_a_real_shaped_client(self):
        cli = _RealShapedClient({"message": {"content": "ok"}})
        resp = llm_io.chat("s", "u", act="plan", client=cli)   # would TypeError if forwarded
        self.assertEqual(llm_io.responseText(resp), "ok")
        self.assertEqual(cli.calls, 1)

    def test_pydantic_response_parity(self):
        cli = _ActAwareClient([_Resp('{"a": 1}')])
        resp = llm_io.chat("s", "u", act="plan", want_json=True, client=cli)
        self.assertEqual(llm_io.responseJson(resp), {"a": 1})

    def test_retry_then_success(self):
        cli = _ActAwareClient([ConnectionError("down"), {"message": {"content": "recovered"}}])
        sleeps = []
        resp = llm_io.chat(
            "s",
            "u",
            act="plan",
            retries=3,
            client=cli,
            sleep_fn=sleeps.append,
            jitter_fn=lambda low, high: high,
        )
        self.assertEqual(llm_io.responseText(resp), "recovered")
        self.assertEqual(len(cli.calls), 2)
        self.assertEqual(sleeps, [2.4])

    def test_returns_none_after_retries_exhausted(self):
        cli = _ActAwareClient([ConnectionError("down")] * 3)
        self.assertIsNone(
            llm_io.chat(
                "s",
                "u",
                act="plan",
                retries=3,
                client=cli,
                sleep_fn=lambda _delay: None,
                jitter_fn=lambda low, high: low,
            )
        )

    def test_empty_completion_salvaged_by_dropping_format_json(self):
        cli = _ActAwareClient([{"message": {"content": ""}},          # format=json dead-end
                               {"message": {"content": '{"a": 1}'}}])  # free-form salvage
        resp = llm_io.chat("s", "u", act="plan", want_json=True, client=cli)
        self.assertEqual(llm_io.responseJson(resp), {"a": 1})
        self.assertEqual(cli.calls[0]["kwargs"].get("format"), "json")
        self.assertNotIn("format", cli.calls[1]["kwargs"])   # salvage drops format=json

    def test_response_extraction_is_pure_and_chat_emits_telemetry_once(self):
        cli = _ActAwareClient([{"message": {"content": '{"ok": 1}'}}])
        with mock.patch.object(llm_io, "_tap_brain") as tap:
            resp = llm_io.chat("system", "actual user prompt", act="plan", client=cli)
            self.assertEqual(llm_io.responseText(resp), '{"ok": 1}')
            self.assertEqual(llm_io.responseText(resp), '{"ok": 1}')
            self.assertEqual(llm_io.responseJson(resp), {"ok": 1})
        tap.assert_called_once_with("actual user prompt", '{"ok": 1}')

    def test_telemetry_failure_never_blanks_an_accepted_completion(self):
        cli = _ActAwareClient([{"message": {"content": "valid"}}])
        with mock.patch.object(llm_io, "_tap_brain", side_effect=RuntimeError("tap down")):
            resp = llm_io.chat("s", "u", act="plan", client=cli)
        self.assertEqual(llm_io.responseText(resp), "valid")

    def test_zero_retries_means_one_attempt_and_logs_one_of_one(self):
        cli = _ActAwareClient([ConnectionError("down")])
        with self.assertLogs(llm_io.LOG, level="WARNING") as captured:
            result = llm_io.chat(
                "s", "u", act="plan", retries=0, client=cli, sleep_fn=lambda _delay: None
            )
        self.assertIsNone(result)
        self.assertEqual(len(cli.calls), 1)
        self.assertIn("attempt 1/1", captured.output[0])

    def test_empty_ordinary_completion_retries_instead_of_becoming_success(self):
        cli = _ActAwareClient(
            [{"message": {"content": ""}}, {"message": {"content": "recovered"}}]
        )
        sleeps = []
        resp = llm_io.chat(
            "s",
            "u",
            act="plan",
            retries=2,
            client=cli,
            sleep_fn=sleeps.append,
            jitter_fn=lambda low, high: 2.0,
        )
        self.assertEqual(llm_io.responseText(resp), "recovered")
        self.assertEqual(sleeps, [2.0])

    def test_client_contract_type_error_is_not_retried(self):
        cli = _ActAwareClient([TypeError("bad client signature"), {"message": {"content": "no"}}])
        with self.assertRaisesRegex(TypeError, "bad client signature"):
            llm_io.chat(
                "s", "u", act="plan", retries=3, client=cli, sleep_fn=lambda _delay: None
            )
        self.assertEqual(len(cli.calls), 1)

    def test_invalid_generation_option_values_fail_before_calling_client(self):
        for options in (
            {"temperature": "hot"},
            {"top_p": -0.1},
            {"seed": []},
        ):
            cli = _ActAwareClient([{"message": {"content": "no"}}])
            with self.assertRaises(ValueError):
                llm_io.chat("s", "u", act="plan", client=cli, generation_options=options)
            self.assertEqual(cli.calls, [])

    def test_client_reset_is_explicit(self):
        sentinel = object()
        original = llm_io._CLIENT
        try:
            llm_io._CLIENT = sentinel
            self.assertIsNone(llm_io.resetClient())
            self.assertIsNone(llm_io._CLIENT)
        finally:
            llm_io._CLIENT = original
