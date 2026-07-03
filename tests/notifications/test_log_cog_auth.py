"""Regression tests: LogCog's `_bang_listener` and `/prefs reset` had no authorization check at
all -- any non-bot user in the control channel could mutate the shared user_prefs.json (global
operator preferences and persistent intents) via `!brief set ...` or `/prefs reset`."""
import asyncio
import importlib
import unittest
from unittest import mock

from notifications import commands as spine


def _fresh_log_cog_module():
    """Re-fetch the log_cog module from sys.modules rather than binding it once at file-import
    time: tests/test_bot_cogs.py loads it as a real discord.py extension, which replaces the
    sys.modules entry with a NEW module object. A LogCog class captured before that swap has
    `_bang_listener.__globals__` pointing at the OLD module dict, so string-based
    `mock.patch("notifications.bot.cogs.log_cog.X", ...)` (which always resolves against the
    CURRENT sys.modules entry) would silently patch a name the running code never reads --
    order-dependent on whatever other test last reloaded the extension."""
    return importlib.import_module("notifications.bot.cogs.log_cog")


class _FakeAuthor:
    def __init__(self, is_bot=False, uid=999):
        self.bot = is_bot
        self.id = uid


class _FakeChannel:
    def __init__(self, cid=0):
        self.id = cid
        self.send = mock.AsyncMock()


class _FakeMessage:
    def __init__(self, content, uid=999, cid=0):
        self.author = _FakeAuthor(uid=uid)
        self.content = content
        self.channel = _FakeChannel(cid)


async def _sync_to_thread(fn, *a, **k):
    """Run the callable inline instead of on a real worker thread -- avoids relying on the
    default ThreadPoolExecutor tied to whatever event loop is current (flaky/order-dependent
    when another test's asyncio.run() + discord.py Bot teardown ran earlier in the process)."""
    return fn(*a, **k)


class TestBangListenerAuth(unittest.TestCase):
    def _run(self, message, authorized):
        log_cog_mod = _fresh_log_cog_module()
        cog = log_cog_mod.LogCog(bot=mock.MagicMock())
        with mock.patch.object(spine, "isAuthorized", return_value=authorized), \
             mock.patch("notifications.bot.cogs.log_cog.config") as cfg, \
             mock.patch("notifications.bot.cogs.log_cog.spine.resolveTargetTask",
                        return_value=object()), \
             mock.patch("notifications.bot.cogs.log_cog.user_prefs.load", return_value={}), \
             mock.patch("notifications.bot.cogs.log_cog.dispatchBang",
                        return_value="mutated") as dispatch, \
             mock.patch("notifications.bot.cogs.log_cog.asyncio.to_thread",
                        side_effect=_sync_to_thread):
            cfg.DISCORD_CHANNEL_ID = 0
            asyncio.run(cog._bang_listener(message))
        return dispatch, message

    def test_unauthorized_user_is_ignored(self):
        dispatch, message = self._run(_FakeMessage("!brief set cost off"), authorized=False)
        dispatch.assert_not_called()
        message.channel.send.assert_not_awaited()

    def test_authorized_user_proceeds(self):
        dispatch, message = self._run(_FakeMessage("!brief set cost off"), authorized=True)
        dispatch.assert_called_once()
        message.channel.send.assert_awaited()


class TestPrefsResetAuth(unittest.TestCase):
    def _run(self, action, guard_ok):
        log_cog_mod = _fresh_log_cog_module()
        cog = log_cog_mod.LogCog(bot=mock.MagicMock())
        interaction = mock.MagicMock()
        interaction.user.id = 4242
        with mock.patch("notifications.bot.cogs.log_cog.slash._guard",
                        new=mock.AsyncMock(return_value=guard_ok)) as guard, \
             mock.patch("notifications.bot.cogs.log_cog.slash._runControl",
                        new=mock.AsyncMock()) as run_control:
            asyncio.run(cog.prefs.callback(cog, interaction, action))
        return guard, run_control

    def test_reset_is_gated(self):
        guard, run_control = self._run("reset", guard_ok=False)
        guard.assert_awaited_once()
        run_control.assert_not_awaited()

    def test_reset_proceeds_when_authorized(self):
        guard, run_control = self._run("reset", guard_ok=True)
        run_control.assert_awaited_once()

    def test_show_is_not_gated(self):
        guard, run_control = self._run("show", guard_ok=False)
        guard.assert_not_awaited()
        run_control.assert_awaited_once()

    def test_no_action_is_not_gated(self):
        guard, run_control = self._run(None, guard_ok=False)
        guard.assert_not_awaited()
        run_control.assert_awaited_once()


class TestPrefsRegistryMutatingFlag(unittest.TestCase):
    def test_prefs_registered_as_mutating(self):
        # COMMAND_REGISTRY["mutating"] is the SOLE authorization gate in
        # views_control.py::_applyControl and the sole audit trigger in
        # slash.py::_runControl -- both are per-command, not per-arg, so "prefs" (whose
        # "reset" sub-action mutates shared state) must be registered mutating=True.
        self.assertTrue(spine.COMMAND_REGISTRY["prefs"]["mutating"])

