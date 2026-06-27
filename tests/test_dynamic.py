"""Tests for the per-subtask DynamicItem (Tier 2): template matching, custom_id minting,
pure routing (skip/inspect/auth), and offline registration. No gateway connection."""
import re
import unittest

import discord

from notifications.bot.ui import dynamic


class _StubState:
    task_id = "t123"
    subtasks = [{"subtask_id": "st-003", "title": "cockpit", "status": "in_progress",
                 "attempts": 2, "verify_result": {"passed": False}}]


class Template(unittest.TestCase):
    def test_matches_skip_and_inspect(self):
        m = re.fullmatch(dynamic.TEMPLATE, "nc:st:skip:st-003")
        self.assertEqual((m["action"], m["sid"]), ("skip", "st-003"))
        m2 = re.fullmatch(dynamic.TEMPLATE, "nc:st:inspect:st-012")
        self.assertEqual((m2["action"], m2["sid"]), ("inspect", "st-012"))

    def test_rejects_unknown_action(self):
        self.assertIsNone(re.fullmatch(dynamic.TEMPLATE, "nc:st:delete:st-001"))

    def test_button_custom_id(self):
        btn = dynamic.subtaskButton("skip", "st-003")
        self.assertEqual(btn.item.custom_id, "nc:st:skip:st-003")


class Routing(unittest.TestCase):
    def setUp(self):
        self._orig = (dynamic.spine.resolveTargetTask, dynamic.spine.isAuthorized,
                      dynamic.spine.applyCommand, dynamic.audit.record, dynamic.ControlBus)
        dynamic.spine.resolveTargetTask = lambda: _StubState()
        dynamic.audit.record = lambda *a, **k: None
        dynamic.ControlBus = lambda tid: object()
        self.applied = []
        dynamic.spine.applyCommand = lambda bus, st, cmd: self.applied.append(cmd) or f"skipped {cmd.arg}"

    def tearDown(self):
        (dynamic.spine.resolveTargetTask, dynamic.spine.isAuthorized,
         dynamic.spine.applyCommand, dynamic.audit.record, dynamic.ControlBus) = self._orig

    def test_inspect_is_readonly(self):
        dynamic.spine.isAuthorized = lambda uid: False   # inspect must NOT require auth
        out = dynamic.applySubtaskAction("inspect", "st-003", 1)
        self.assertIn("st-003", out)
        self.assertIn("cockpit", out)
        self.assertEqual(self.applied, [])

    def test_skip_requires_auth(self):
        dynamic.spine.isAuthorized = lambda uid: False
        out = dynamic.applySubtaskAction("skip", "st-003", 1)
        self.assertIn("Not authorized", out)
        self.assertEqual(self.applied, [])

    def test_skip_routes_to_spine(self):
        dynamic.spine.isAuthorized = lambda uid: True
        out = dynamic.applySubtaskAction("skip", "st-003", 1)
        self.assertEqual(len(self.applied), 1)
        self.assertEqual((self.applied[0].name, self.applied[0].arg), ("skip", "st-003"))
        self.assertIn("skipped st-003", out)

    def test_no_task(self):
        dynamic.spine.resolveTargetTask = lambda: None
        dynamic.spine.isAuthorized = lambda uid: True
        self.assertEqual(dynamic.applySubtaskAction("inspect", "st-003", 1), dynamic.spine.NO_TASK)


class Registration(unittest.TestCase):
    def test_add_dynamic_items_offline(self):
        from discord.ext import commands as dpy_commands
        intents = discord.Intents.default()
        bot = dpy_commands.Bot(command_prefix=dpy_commands.when_mentioned, intents=intents)
        bot.add_dynamic_items(dynamic.SubtaskButton)   # must not raise


if __name__ == "__main__":
    unittest.main()
