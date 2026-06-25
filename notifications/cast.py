"""The Cast -- speak() routes an agent's voice through its webhook persona.

A thin, safe facade over ``discord_bot.sendAs`` + ``personas``. Gated by
``config.CAST_MODE`` (off by default -> a silent no-op, zero behaviour change), and
respects night mode for non-critical lines. The orchestrator calls
``cast.speak("architect", text)`` etc. at each agent's voice point; when CAST_MODE
is off these calls cost nothing and emit nothing.
"""
from __future__ import annotations

from typing import Optional

import config
from notifications import discord_bot as discord
from notifications import personas

LOG = config.getLogger("cast")


def enabled() -> bool:
    return bool(config.CAST_MODE)


def speak(role: str, text: Optional[str] = None, *, embed: Optional[dict] = None,
          components: Optional[list] = None, files: Optional[list] = None,
          thread_id: Optional[str] = None, milestone: bool = False) -> bool:
    """Post AS the persona for ``role``. No-op (returns False) when CAST_MODE is off, or when this
    is a non-critical ``milestone`` during night mode. Never raises -- The Cast is best-effort."""
    if not config.CAST_MODE:
        return False
    if milestone and config.NIGHT_MODE:
        return False
    if not (text or embed or components):
        return False
    try:
        return discord.sendAs(personas.persona(role), content=text, embed=embed,
                              components=components, files=files, thread_id=thread_id)
    except Exception:  # noqa: BLE001 -- a webhook hiccup must never break a run
        LOG.warning("cast.speak(%s) failed", role, exc_info=True)
        return False
