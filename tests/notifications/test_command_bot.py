"""Unit tests for the command_bot.handleCommand() spine (no gateway needed)."""
import unittest
from unittest import mock

import config
from notifications import command_bot as cb
from notifications import commands
from state.task import TaskState


def _state():
    st = TaskState.create("test goal", 1.0)
    st.meta["status"] = "executing"
    return st


class TestHandleCommand(unittest.TestCase):
    def test_non_command_returns_empty(self):
        self.assertEqual(cb.handleCommand("hello world"), "")

    def test_unknown_command_returns_empty(self):
        self.assertEqual(cb.handleCommand("!frobnicate"), "")

    def test_no_task_returns_no_task_message(self):
        with mock.patch.object(commands, "resolveTargetTask", return_value=None):
            result = cb.handleCommand("!status")
        self.assertEqual(result, commands.NO_TASK)

    def test_valid_command_delegated_to_spine(self):
        st = _state()
        bus_mock = mock.Mock()
        with mock.patch.object(commands, "resolveTargetTask", return_value=st), \
             mock.patch("platform_core.runtime.control.ControlBus", return_value=bus_mock), \
             mock.patch.object(commands, "applyCommand", return_value="aborted") as apply_mock:
            result = cb.handleCommand("!abort")
        self.assertEqual(result, "aborted")
        apply_mock.assert_called_once()
        call_cmd = apply_mock.call_args[0][2]
        self.assertEqual(call_cmd.name, "abort")

    def test_command_with_arg_passed_through(self):
        st = _state()
        bus_mock = mock.Mock()
        with mock.patch.object(commands, "resolveTargetTask", return_value=st), \
             mock.patch("platform_core.runtime.control.ControlBus", return_value=bus_mock), \
             mock.patch.object(commands, "applyCommand", return_value="added") as apply_mock:
            cb.handleCommand("!add write a parser")
        call_cmd = apply_mock.call_args[0][2]
        self.assertEqual(call_cmd.name, "add")
        self.assertEqual(call_cmd.arg, "write a parser")

    def test_max_reply_constant_below_discord_limit(self):
        self.assertLess(cb.MAX_REPLY_CHARS, config.DISCORD_MAX_CONTENT)
