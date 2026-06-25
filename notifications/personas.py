"""The Cast -- the 9to5 agent roster used for webhook identity overrides.

Each agent role maps to a persona ``{name, emoji, color, avatar_url}`` so the run
reads like a live writers'-room: the Adversary speaks under ⚔️, the Executor under
⚙️, the Brain under 🧠. Per-message avatars require a hosted URL, so by default
personas are distinguished by their emoji-bearing name + accent color; an optional
per-role avatar URL can be supplied via env (NIGHTCLAW_AVATAR_<ROLE>).

Pure data + lookup; no network, no discord.py.
"""
from __future__ import annotations

import os

import config


def _avatar(role: str) -> str:
    return os.getenv(f"NIGHTCLAW_AVATAR_{role.upper()}", config.BRAND_ICON_URL or "")


CAST: dict[str, dict] = {
    "brain":     {"name": "Nightclaw · Brain 🧠",     "emoji": "🧠", "color": 0x5865F2},
    "orchestrator": {"name": "Nightclaw · Brain 🧠",  "emoji": "🧠", "color": 0x5865F2},
    "architect": {"name": "Nightclaw · Architect 📐", "emoji": "📐", "color": 0x3498DB},
    "planner":   {"name": "Nightclaw · Planner 🗺️",   "emoji": "🗺️", "color": 0x3498DB},
    "executor":  {"name": "Nightclaw · Executor ⚙️",  "emoji": "⚙️", "color": 0x2ECC71},
    "verifier":  {"name": "Nightclaw · Verifier 🔎",  "emoji": "🔎", "color": 0x1ABC9C},
    "adversary": {"name": "Nightclaw · Adversary ⚔️", "emoji": "⚔️", "color": 0xE67E22},
    "replanner": {"name": "Nightclaw · Replanner 🔁", "emoji": "🔁", "color": 0x9B59B6},
}


def persona(role: str) -> dict:
    """Resolve a role to its persona dict (falls back to Brain), with avatar_url filled in."""
    key = (role or "").lower().strip()
    if key not in CAST:
        key = "brain"
    p = dict(CAST[key])
    p["avatar_url"] = _avatar(key)
    return p


def roles() -> tuple:
    return tuple(k for k in CAST if k != "orchestrator")
