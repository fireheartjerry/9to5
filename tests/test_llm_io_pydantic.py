"""Regression guard for the empty-completion ROOT CAUSE: the ollama-python client returns
pydantic ChatResponse/Message objects (NOT dicts), and the old isinstance(resp, dict) gate
threw away the content of every real reply -> "Brain (Ollama) unavailable; empty completion".

These objects support attribute access (resp.message.content), subscript, and .get(), but are
NOT dict instances. llm_io.responseText/responseJson (and orchestrator._chatText/_chatJson which
delegate to them) must extract from them while still returning ''/None for malformed shapes.
"""
import unittest

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
