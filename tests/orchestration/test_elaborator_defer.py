import unittest
from unittest import mock
from agents.planning.elaborator import defer


class TestMaybeDefer(unittest.TestCase):
    def _on(self):
        return mock.patch.object(__import__("config"), "ELABORATOR_DEFER_ENABLED", True)

    def test_no_defer_returns_local(self):
        called = {"n": 0}
        def esc(goal):
            called["n"] += 1
            return "BIG"
        with self._on():
            out = defer.maybeDefer("LOCAL", "g", {"defer": False}, escalate_fn=esc)
        self.assertEqual(out, "LOCAL")
        self.assertEqual(called["n"], 0)

    def test_defer_returns_escalated(self):
        with self._on():
            out = defer.maybeDefer("LOCAL", "g", {"defer": True}, escalate_fn=lambda goal: "BIG SPEC")
        self.assertEqual(out, "BIG SPEC")

    def test_defer_empty_escalation_keeps_local(self):
        with self._on():
            out = defer.maybeDefer("LOCAL", "g", {"defer": True}, escalate_fn=lambda goal: "")
        self.assertEqual(out, "LOCAL")

    def test_defer_raising_escalation_keeps_local(self):
        def boom(goal):
            raise RuntimeError("claude down")
        with self._on():
            out = defer.maybeDefer("LOCAL", "g", {"defer": True}, escalate_fn=boom)
        self.assertEqual(out, "LOCAL")

    def test_flag_off_never_escalates(self):
        called = {"n": 0}
        def esc(goal):
            called["n"] += 1
            return "BIG"
        with mock.patch.object(__import__("config"), "ELABORATOR_DEFER_ENABLED", False):
            out = defer.maybeDefer("LOCAL", "g", {"defer": True}, escalate_fn=esc)
        self.assertEqual(out, "LOCAL")
        self.assertEqual(called["n"], 0)
