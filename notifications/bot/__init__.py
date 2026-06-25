"""9TO5 "Nightclaw" gateway bot package.

A discord.py ``commands.Bot`` (``bot.core.NightclawBot``) organised into
hot-reloadable extension cogs (``bot/cogs/``) and reusable UI (``bot/ui/``).

This package is the GATEWAY side only. It must never be imported by the
synchronous orchestrator process -- that side drives Discord exclusively through
the raw-REST layer (``notifications.discord_bot``) and the pure command spine
(``notifications.commands``). Both processes share that spine + the ``ControlBus``;
neither depends on the other's transport.

Importing this package is cheap and discord-free; the heavy ``discord`` import
lives inside ``bot.core`` so tooling can introspect the package without a gateway.
"""
from __future__ import annotations
