"""Gateway command bot -- slim shell. Registers the slash command suite (slash.py),
persistent component views (views.py), a presence loop, and the legacy '!' text path
(via the commands.py spine). Run:  venv\\Scripts\\python -m notifications.command_bot
"""
from __future__ import annotations

import asyncio
import time

import config
from control import ControlBus
from notifications import commands
from state.task import TaskState  # noqa: F401  (kept for parity / external imports)

LOG = config.getLogger("command_bot")

MAX_REPLY_CHARS = config.DISCORD_MAX_CONTENT - 100


def handleCommand(content: str) -> str:
    """Parse + apply a '!' command against the latest task. '' if not a command."""
    cmd = commands.parseCommand(content)
    if cmd is None:
        return ""
    state = commands.resolveTargetTask()
    if state is None:
        return commands.NO_TASK
    return commands.applyCommand(ControlBus(state.task_id), state, cmd)


def runCommandBot() -> None:  # pragma: no cover -- long-lived gateway process
    import discord as dpy
    from discord import app_commands
    from notifications import audit, slash, views

    if not config.DISCORD_BOT_TOKEN:
        LOG.error("DISCORD_BOT_TOKEN missing; cannot start command bot")
        return

    started_at = time.time()
    intents = dpy.Intents.default()
    intents.message_content = True
    client = dpy.Client(intents=intents)
    tree = app_commands.CommandTree(client)
    slash.registerSlashCommands(tree, client, started_at)
    _state = {"synced": False, "presence": False}

    @tree.error
    async def _on_app_error(interaction, error):  # noqa: ANN001
        if isinstance(error, app_commands.CommandOnCooldown):
            msg = f"⏳ Slow down — try again in {error.retry_after:.0f}s."
        else:
            LOG.exception("slash error: %s", error)
            msg = "internal error (see logs)"
        try:
            if interaction.response.is_done():
                await interaction.followup.send(msg, ephemeral=True)
            else:
                await interaction.response.send_message(msg, ephemeral=True)
        except Exception:  # noqa: BLE001
            pass

    async def _presenceLoop():
        await client.wait_until_ready()
        while not client.is_closed():
            try:
                state = commands.resolveTargetTask()
                if state is not None and commands.isRunActive(state):
                    done, total = state.progress()
                    name = f"{done}/{total} · {state.meta.get('status', 'run')}"
                else:
                    name = "idle · /help"
                await client.change_presence(
                    activity=dpy.Activity(type=dpy.ActivityType.watching, name=name))
            except Exception:  # noqa: BLE001
                pass
            await asyncio.sleep(config.PRESENCE_INTERVAL)

    @client.event
    async def on_ready() -> None:
        if not _state["synced"]:
            try:
                if config.DISCORD_GUILD_ID:
                    guild = dpy.Object(id=config.DISCORD_GUILD_ID)
                    tree.copy_global_to(guild=guild)
                    synced = await tree.sync(guild=guild)
                else:
                    synced = await tree.sync()
                _state["synced"] = True
                LOG.info("Command bot online as %s; synced %d slash command(s)", client.user, len(synced))
            except Exception as e:  # noqa: BLE001
                LOG.warning("slash sync failed: %s", e)
        client.add_view(views.ControlPanelView())   # persistent: matches cp_* on any message
        client.add_view(views.BlockedView())        # persistent: matches sc_*
        if not _state["presence"]:
            _state["presence"] = True
            client.loop.create_task(_presenceLoop())

    @client.event
    async def on_message(message: "dpy.Message") -> None:
        if message.author == client.user or not message.content.strip().startswith("!"):
            return
        if not commands.isAuthorized(message.author.id):
            LOG.info("ignored '!' command from unauthorized user %s", message.author.id)
            return
        if config.DISCORD_CHANNEL_ID and message.channel.id != config.DISCORD_CHANNEL_ID:
            return
        try:
            reply = handleCommand(message.content)
        except Exception:  # noqa: BLE001
            LOG.exception("command error")
            reply = "internal error (see logs)"
        if reply:
            await message.channel.send(reply[:MAX_REPLY_CHARS])

    client.run(config.DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    runCommandBot()
