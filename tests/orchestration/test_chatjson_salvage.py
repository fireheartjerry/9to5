"""The brain-JSON salvage in orchestrator._chatJson must extract the FIRST balanced object, not the
greedy first-'{'-to-last-'}' span. Multi-object output (an example + the real plan, or trailing prose
with braces) used to concatenate into an unparseable blob, collapsing the plan/spec to a fallback."""
import unittest
from unittest import mock

import orchestrator


class TestChatJsonSalvage(unittest.TestCase):
    def _chatjson(self, text):
        with mock.patch.object(orchestrator, "_chatText", return_value=text):
            return orchestrator._chatJson(object())

    def test_recovers_first_object_with_trailing_braces(self):
        out = self._chatjson('{"subtasks": [{"title": "a"}]}\n\nExample to ignore: {oops}')
        self.assertIsInstance(out, dict)
        self.assertEqual(out["subtasks"][0]["title"], "a")

    def test_recovers_object_after_leading_prose(self):
        out = self._chatjson('Sure! Here is the plan:\n```json\n{"approve": true}\n```')
        self.assertEqual(out.get("approve"), True)

    def test_clean_json_passthrough(self):
        self.assertEqual(self._chatjson('{"x": 1}'), {"x": 1})

    def test_garbage_returns_none(self):
        self.assertIsNone(self._chatjson("no json here at all"))
