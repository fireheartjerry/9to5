"""Unit tests for the pure command spine (no gateway needed)."""
import unittest
from unittest import mock

import config
from notifications import commands
from state.task import TaskState


def _state(status="executing"):
    st = TaskState.create("test goal", 1.0)
    st.meta["status"] = status
    return st


class TestParseCommand(unittest.TestCase):
    def test_non_bang_returns_none(self):
        self.assertIsNone(commands.parseCommand("hello"))

    def test_unknown_returns_none(self):
        self.assertIsNone(commands.parseCommand("!frobnicate"))

    def test_exact_token_match(self):
        cmd = commands.parseCommand("!abort")
        self.assertEqual(cmd.name, "abort")
        self.assertEqual(cmd.arg, "")

    def test_skipfoo_does_not_match_skip(self):
        self.assertIsNone(commands.parseCommand("!skipfoo"))

    def test_add_arg_sliced_correctly(self):
        cmd = commands.parseCommand("!add write a parser")
        self.assertEqual(cmd.name, "add")
        self.assertEqual(cmd.arg, "write a parser")

    def test_skip_arg(self):
        cmd = commands.parseCommand("!skip st-003")
        self.assertEqual((cmd.name, cmd.arg), ("skip", "st-003"))


class TestIsAuthorized(unittest.TestCase):
    def test_unset_allows_all(self):
        with mock.patch.object(config, "DISCORD_HUMAN_USER_ID", ""):
            self.assertTrue(commands.isAuthorized(12345))
            self.assertTrue(commands.isAuthorized(None))

    def test_blank_string_no_crash(self):
        with mock.patch.object(config, "DISCORD_HUMAN_USER_ID", "   "):
            self.assertTrue(commands.isAuthorized(1))

    def test_set_owner_only(self):
        with mock.patch.object(config, "DISCORD_HUMAN_USER_ID", "777"):
            self.assertTrue(commands.isAuthorized(777))
            self.assertTrue(commands.isAuthorized("777"))
            self.assertFalse(commands.isAuthorized(778))
            self.assertFalse(commands.isAuthorized(None))


class TestDecide(unittest.TestCase):
    def test_bot_author_blocked(self):
        with mock.patch.object(config, "DISCORD_HUMAN_USER_ID", ""):
            self.assertIsNone(commands.decide(1, True, "!abort"))

    def test_unauthorized_blocked(self):
        with mock.patch.object(config, "DISCORD_HUMAN_USER_ID", "777"):
            self.assertIsNone(commands.decide(778, False, "!abort"))

    def test_authorized_passes(self):
        with mock.patch.object(config, "DISCORD_HUMAN_USER_ID", "777"):
            cmd = commands.decide(777, False, "!abort")
            self.assertEqual(cmd.name, "abort")


class TestIsRunActive(unittest.TestCase):
    def test_terminal_inactive(self):
        for s in TaskState._TERMINAL:
            self.assertFalse(commands.isRunActive(_state(s)), s)

    def test_executing_active(self):
        self.assertTrue(commands.isRunActive(_state("executing")))


class TestApplyCommand(unittest.TestCase):
    def test_reject_copy_is_rejected_not_rejectd(self):
        st = _state("executing")
        bus = mock.Mock()
        bus.getPendingGate.return_value = "plan"
        out = commands.applyCommand(bus, st, commands.Command("reject", ""))
        self.assertIn("rejected", out.lower())
        self.assertNotIn("rejectd", out.lower())
        bus.decide.assert_called_once_with("plan", "reject")

    def test_skip_bad_id_rejected(self):
        st = _state("executing")
        bus = mock.Mock()
        out = commands.applyCommand(bus, st, commands.Command("skip", "garbage"))
        self.assertIn("usage", out.lower())
        bus.pushOp.assert_not_called()

    def test_abort_mutates_bus(self):
        st = _state("executing")
        bus = mock.Mock()
        commands.applyCommand(bus, st, commands.Command("abort", ""))
        bus.requestAbort.assert_called_once()


if __name__ == "__main__":
    unittest.main()
