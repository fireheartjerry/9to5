"""§7.5 escalation transport: re-elaborate a goal via a more capable model."""
import unittest
from unittest import mock

from agents.planning.elaborator import escalate


class TestEscalate(unittest.TestCase):
    def test_injected_chat_returns_spec(self):
        def chat(system, user, *, act, want_json=False):
            return {"message": {"content": "BIG SPEC"}}
        self.assertEqual(escalate.escalateToModel("g", chat=chat), "BIG SPEC")

    def test_inert_when_no_model_and_no_chat(self):
        with mock.patch.object(__import__("config"), "ELABORATOR_DEFER_MODEL", ""):
            self.assertEqual(escalate.escalateToModel("g"), "")

    def test_raising_chat_degrades_to_empty(self):
        def boom(*a, **k):
            raise RuntimeError("model down")
        self.assertEqual(escalate.escalateToModel("g", chat=boom), "")
