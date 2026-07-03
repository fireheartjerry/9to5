"""B20/B21: /abort offloads its blocking ControlBus IO off the gateway loop, and the '!'
on_message path ignores ALL bot authors (not just this bot). No token, no network."""
import asyncio
import unittest
from unittest import mock

import config
from notifications import commands as spine
from notifications.bot import core
from notifications.bot.cogs.control_cog import ControlCog


class _FakeState:
    task_id = "t-abort-1"
    meta = {"status": "running"}


class TestAbortOffloads(unittest.TestCase):
    """B20: the /abort coroutine must run applyCommand via asyncio.to_thread, never inline."""

    def test_abort_offloads_to_thread(self):
        cog = ControlCog(bot=mock.MagicMock())
        interaction = mock.MagicMock()
        interaction.user.id = 4242
        interaction.followup.send = mock.AsyncMock()

        to_thread = mock.AsyncMock(return_value="aborted")
        with mock.patch("notifications.slash._guard", new=mock.AsyncMock(return_value=True)), \
             mock.patch("notifications.views.confirmDestructive",
                        new=mock.AsyncMock(return_value=True)), \
             mock.patch.object(spine, "resolveTargetTask", return_value=_FakeState()), \
             mock.patch("notifications.audit.record"), \
             mock.patch("notifications.bot.cogs.control_cog.asyncio.to_thread", new=to_thread):
            asyncio.run(cog.abort.callback(cog, interaction))

        self.assertTrue(to_thread.called, "abort did not offload applyCommand to a thread")
        # The offloaded callable must be the blocking applyCommand.
        self.assertIs(to_thread.call_args.args[0], spine.applyCommand)
        interaction.followup.send.assert_awaited()


class _FakeAuthor:
    def __init__(self, is_bot, uid=999):
        self.bot = is_bot
        self.id = uid


class _FakeChannel:
    def __init__(self, cid=0):
        self.id = cid
        self.send = mock.AsyncMock()


class _FakeMessage:
    def __init__(self, is_bot, content="!abort", cid=0, mid=1):
        self.author = _FakeAuthor(is_bot)
        self.content = content
        self.channel = _FakeChannel(cid)
        self.id = mid


class TestOnMessageIgnoresBots(unittest.TestCase):
    """B21: a bot-authored '!' command must be ignored before any control IO runs."""

    def _run_on_message(self, message):
        bot = core.buildBot()
        # DISCORD_CHANNEL_ID falsy -> skip the channel filter; isAuthorized always True so the
        # ONLY thing that can gate a human message here is the bot-author check under test.
        with mock.patch.object(config, "DISCORD_CHANNEL_ID", 0), \
             mock.patch.object(spine, "isAuthorized", return_value=True), \
             mock.patch.object(core, "handleCommand", return_value="") as handle:
            asyncio.run(bot.on_message(message))
        return handle, message

    def test_bot_authored_command_ignored(self):
        handle, message = self._run_on_message(_FakeMessage(is_bot=True))
        handle.assert_not_called()
        message.channel.send.assert_not_awaited()

    def test_human_authored_command_proceeds(self):
        # Contrast: identical message from a non-bot author DOES reach handleCommand,
        # proving the guard keys on author.bot rather than blocking everything.
        handle, message = self._run_on_message(_FakeMessage(is_bot=False))
        handle.assert_called_once()

