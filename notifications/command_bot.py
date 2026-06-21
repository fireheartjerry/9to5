"""Gateway command bot -- rich, interactive Discord control.

Runs as its own long-lived process:

    venv\\Scripts\\python -m notifications.command_bot

It always targets the most recent task and writes commands to that task's
ControlBus, which the running orchestrator drains between steps.

Commands:
  !status                current phase, subtask X/Y, elapsed/ETA
  !plan                  full subtask list with statuses
  !log                   Obsidian index note path + web dashboard URL
  !abort                 graceful stop after the current step
  !pause / !resume       hold / continue the run
  !approve / !reject     answer the pending approval gate (gated mode)
  !skip <st-00N>         drop a pending subtask
  !add <title>           queue a new subtask
  !retry                 re-run the current subtask
"""
from __future__ import annotations

from datetime import datetime

import config
from control import ControlBus
from state.task import TaskState

LOG = config.getLogger("command_bot")


def _fmtDelta(seconds: float) -> str:
    seconds = max(0, int(seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}h{m:02d}m{s:02d}s"


def handleCommand(content: str) -> str:
    """Pure command handler (also unit-testable without a gateway)."""
    parts = content.strip().split(maxsplit=1)
    cmd = parts[0].lower()
    arg = parts[1].strip() if len(parts) > 1 else ""

    state = TaskState.loadLatest()
    if state is None:
        return "No 9TO5 task on record yet."
    bus = ControlBus(state.task_id)

    if cmd == "!status":
        done, total = state.progress()
        try:
            started = datetime.fromisoformat(state.meta["started_at"])
            deadline = datetime.fromisoformat(state.meta["deadline_at"])
            now = datetime.now().astimezone()
            elapsed = _fmtDelta((now - started).total_seconds())
            eta = _fmtDelta((deadline - now).total_seconds())
        except Exception:  # noqa: BLE001
            elapsed = eta = "-"
        cur = next((s for s in state.subtasks if s["status"] == "in_progress"), None) or state.nextActionable()
        cur_txt = f"{cur['subtask_id']} {cur['title']}" if cur else "-"
        gate = bus.getPendingGate()
        gate_txt = f"\n⏳ awaiting gate: **{gate}** (!approve / !reject)" if gate else ""
        return (f"**`{state.meta['status']}`** · subtask {done}/{total} · mode {state.meta.get('control_mode')}\n"
                f"Current: {cur_txt}\nElapsed {elapsed} · ETA {eta}{gate_txt}")

    if cmd == "!plan":
        lines = [f"{s['subtask_id']} [{s['status']}] {s['title']}" for s in state.subtasks]
        return "```\n" + ("\n".join(lines) or "(no subtasks)")[:1800] + "\n```"

    if cmd == "!log":
        return (f"Index: `{state.indexNoteRel()}`\n"
                f"Vault: `{state.data['obsidian']['vault_root']}`\n"
                f"Web: http://127.0.0.1:{config.WEB_DASHBOARD_PORT}/")

    if cmd == "!abort":
        bus.requestAbort()
        return "🛑 abort requested — run will stop after the current step."
    if cmd == "!pause":
        bus.requestPause()
        return "⏸ pause requested."
    if cmd == "!resume":
        bus.clearPause()
        return "▶ resumed."
    if cmd in ("!approve", "!reject"):
        gate = bus.getPendingGate()
        if not gate:
            return "No gate is currently pending."
        bus.decide(gate, "approve" if cmd == "!approve" else "reject")
        return f"Gate **{gate}** → {cmd[1:]}d."
    if cmd == "!skip":
        if not arg:
            return "usage: !skip <st-00N>"
        bus.pushOp({"op": "skip", "subtask_id": arg})
        return f"queued skip of {arg}."
    if cmd == "!add":
        if not arg:
            return "usage: !add <title>"
        bus.pushOp({"op": "add", "title": arg, "description": arg})
        return f"queued new subtask: {arg}"
    if cmd == "!retry":
        bus.pushOp({"op": "retry"})
        return "queued retry of the current subtask."

    return ("commands: !status !plan !log !abort !pause !resume "
            "!approve !reject !skip <id> !add <title> !retry")


def handleButton(custom_id: str) -> str:
    """Handle a Discord component-button click (sc_answer / sc_skip / sc_abort)."""
    state = TaskState.loadLatest()
    if state is None:
        return "No 9TO5 task on record."
    bus = ControlBus(state.task_id)
    if custom_id == "sc_abort":
        bus.requestAbort()
        return "🛑 Abort requested — run stops after the current step."
    if custom_id == "sc_skip":
        cur = next((s for s in state.subtasks if s["status"] == "in_progress"), None)
        if cur:
            bus.pushOp({"op": "skip", "subtask_id": cur["subtask_id"]})
            return f"⏭️ Skipping {cur['subtask_id']}."
        return "Nothing in progress to skip."
    if custom_id == "sc_answer":
        return "✍️ Type your answer as a normal message and the orchestrator will pick it up."
    return "Unknown action."


def runCommandBot() -> None:  # pragma: no cover -- long-lived gateway process
    import discord

    intents = discord.Intents.default()
    intents.message_content = True
    client = discord.Client(intents=intents)

    @client.event
    async def on_ready() -> None:
        LOG.info("Command bot online as %s", client.user)

    @client.event
    async def on_interaction(interaction: "discord.Interaction") -> None:
        try:
            if interaction.type == discord.InteractionType.component:
                reply = handleButton((interaction.data or {}).get("custom_id", ""))
                await interaction.response.send_message(reply)
        except Exception as e:  # noqa: BLE001
            LOG.warning("interaction error: %s", e)

    @client.event
    async def on_message(message: "discord.Message") -> None:
        if message.author == client.user:
            return
        if not message.content.strip().startswith("!"):
            return
        try:
            reply = handleCommand(message.content)
        except Exception as e:  # noqa: BLE001
            reply = f"error: {e}"
        await message.channel.send(reply[:1900])

    if not config.DISCORD_BOT_TOKEN:
        LOG.error("DISCORD_BOT_TOKEN missing; cannot start command bot")
        return
    client.run(config.DISCORD_BOT_TOKEN)


if __name__ == "__main__":
    runCommandBot()
