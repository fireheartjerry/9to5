"""Hot-reloadable feature cogs for the Nightclaw gateway.

Each module exposes an ``async def setup(bot)`` so it can be loaded, unloaded, and
reloaded at runtime via ``bot.load_extension`` / ``reload_extension`` (the
``/reload`` owner command). Cogs are thin: they translate Discord interactions
into calls on the pure ``notifications.commands`` spine + the ``ControlBus`` and
never embed control logic of their own.
"""
from __future__ import annotations
