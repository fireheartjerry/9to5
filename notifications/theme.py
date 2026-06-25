"""Theme engine (T8 keystone) -- the single source of visual identity for the whole frontier
surface: Pillow palettes, ANSI codes, progress glyphs, status accents, phase emoji. Pure, no
network. ``config.COCKPIT_THEME`` selects the active theme; everything (HUD, Pillow cards, the
cockpit accent, future cinematics) reads through here so one toggle re-skins the entire lab.
"""
from __future__ import annotations

import config

# Pillow palettes (RGB tuples): bg / panel / text / muted / grid.
PALETTES = {
    "dark":     {"bg": (24, 26, 33), "panel": (33, 37, 48), "text": (230, 233, 239),
                 "muted": (138, 145, 160), "grid": (52, 58, 74)},
    "neon":     {"bg": (10, 10, 18), "panel": (22, 18, 40), "text": (235, 240, 255),
                 "muted": (150, 130, 200), "grid": (60, 40, 110)},
    "minimal":  {"bg": (250, 250, 252), "panel": (238, 240, 244), "text": (28, 30, 36),
                 "muted": (120, 126, 138), "grid": (210, 214, 222)},
    "terminal": {"bg": (8, 12, 10), "panel": (12, 20, 14), "text": (120, 255, 140),
                 "muted": (70, 150, 90), "grid": (24, 50, 30)},
}

# ANSI frame color per theme (the HUD box border).
ANSI_FRAME = {"dark": "36", "neon": "35", "minimal": "37", "terminal": "32"}

# status -> ANSI fg code (shared across themes).
ANSI_STATUS = {
    "executing": "32", "running": "32", "verifying": "32", "done": "32", "complete": "32",
    "architecting": "36", "planning": "36", "starting": "36", "resuming": "36",
    "adversary": "33", "paused": "33",
    "replanning": "35",
    "blocked": "31", "failed": "31", "aborted": "31",
}

# progress bar glyphs (filled, empty) per theme.
GLYPHS = {
    "dark": ("█", "░"), "neon": ("▰", "▱"), "minimal": ("■", "□"), "terminal": ("#", "-"),
}

# subtask status -> fill color (Pillow), shared.
STATUS_FILL = {
    "done": (46, 204, 113), "in_progress": (52, 152, 219), "failed": (231, 76, 60),
    "pending": (90, 96, 110), "removed": (60, 64, 76),
}

PHASE_EMOJI = {
    "starting": "🚀", "resuming": "↻", "architecting": "📐", "planning": "🗺️",
    "executing": "⚙️", "verifying": "🔎", "replanning": "🔁", "paused": "⏸️",
    "blocked": "🚨", "complete": "✅", "aborted": "🛑", "failed": "❌",
}


def name() -> str:
    return config.COCKPIT_THEME if config.COCKPIT_THEME in PALETTES else "dark"


def pillowPalette() -> dict:
    return PALETTES[name()]


def ansiFrame() -> str:
    return ANSI_FRAME.get(name(), "36")


def ansiStatus(status) -> str:
    return ANSI_STATUS.get(status or "", "37")


def glyphs() -> tuple:
    return GLYPHS.get(name(), ("█", "░"))


def statusFill(status) -> tuple:
    return STATUS_FILL.get(status, STATUS_FILL["pending"])


def accent(status) -> int:
    return config.STATUS_COLORS.get(status or "", config.BRAND_COLOR)


def phaseEmoji(phase) -> str:
    return PHASE_EMOJI.get(phase, "🛰")
