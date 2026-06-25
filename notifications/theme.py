"""Theme engine (T8 keystone) -- the single source of visual identity for the whole frontier
surface: Pillow palettes + FONTS, ANSI codes, progress glyphs, status accents, phase emoji.
Pure (no PIL import at module load; fonts lazy-load on first use). ``config.COCKPIT_THEME``
selects the active theme; everything reads through here so one toggle re-skins the entire lab.

Design language: "Nightclaw Ops Console" -- a premium developer-ops/monitoring aesthetic
(GitHub-dark / Linear / Vercel lineage): semantic color tokens, real type hierarchy
(Segoe UI for UI, Cascadia Mono for data), 4/8 spacing rhythm, drawn vector glyphs (never
emoji on the canvas), tabular figures for metrics.
"""
from __future__ import annotations

from pathlib import Path

import config

# ---- semantic palettes (RGB) ------------------------------------------------
# Keys: bg/bg2 (canvas + gradient end), surface/surface2 (panels), border, text/muted/faint,
# accent + status colors (success/info/warning/danger/purple). 'panel'/'grid' kept as aliases.
PALETTES = {
    "dark": {
        "bg": (13, 17, 23), "bg2": (9, 11, 16), "surface": (22, 27, 34), "surface2": (33, 38, 45),
        "border": (48, 54, 61), "text": (230, 237, 243), "muted": (139, 148, 158), "faint": (87, 96, 109),
        "accent": (88, 166, 255), "success": (63, 185, 80), "info": (88, 166, 255),
        "warning": (210, 153, 34), "danger": (248, 81, 73), "purple": (188, 140, 255),
    },
    "neon": {
        "bg": (10, 10, 20), "bg2": (6, 6, 14), "surface": (22, 18, 42), "surface2": (32, 26, 58),
        "border": (62, 48, 110), "text": (235, 240, 255), "muted": (158, 142, 210), "faint": (104, 92, 150),
        "accent": (124, 92, 255), "success": (54, 226, 168), "info": (90, 170, 255),
        "warning": (255, 196, 84), "danger": (255, 94, 122), "purple": (188, 140, 255),
    },
    "minimal": {  # light theme
        "bg": (255, 255, 255), "bg2": (246, 248, 250), "surface": (255, 255, 255), "surface2": (246, 248, 250),
        "border": (208, 215, 222), "text": (31, 35, 40), "muted": (101, 109, 118), "faint": (140, 149, 159),
        "accent": (9, 105, 218), "success": (26, 127, 55), "info": (9, 105, 218),
        "warning": (154, 103, 0), "danger": (209, 36, 47), "purple": (130, 80, 223),
    },
    "terminal": {
        "bg": (8, 12, 10), "bg2": (4, 7, 5), "surface": (13, 20, 15), "surface2": (18, 28, 21),
        "border": (28, 54, 34), "text": (190, 255, 200), "muted": (96, 170, 116), "faint": (64, 120, 80),
        "accent": (88, 230, 130), "success": (88, 230, 130), "info": (96, 200, 255),
        "warning": (230, 200, 90), "danger": (255, 110, 100), "purple": (180, 160, 255),
    },
}

# subtask status -> palette key (theme-aware fills, no hardcoded RGB)
_STATUS_KEY = {"done": "success", "in_progress": "info", "failed": "danger",
               "pending": "faint", "removed": "border"}

# ANSI (HUD) -- frame per theme + status code (shared); glyphs per theme.
ANSI_FRAME = {"dark": "36", "neon": "35", "minimal": "37", "terminal": "32"}
ANSI_STATUS = {
    "executing": "32", "running": "32", "verifying": "32", "done": "32", "complete": "32",
    "architecting": "36", "planning": "36", "starting": "36", "resuming": "36",
    "adversary": "33", "paused": "33", "replanning": "35",
    "blocked": "31", "failed": "31", "aborted": "31",
}
GLYPHS = {"dark": ("█", "░"), "neon": ("█", "░"), "minimal": ("█", "░"), "terminal": ("#", "-")}

PHASE_EMOJI = {
    "starting": "🚀", "resuming": "↻", "architecting": "📐", "planning": "🗺️",
    "executing": "⚙️", "verifying": "🔎", "replanning": "🔁", "paused": "⏸️",
    "blocked": "🚨", "complete": "✅", "aborted": "🛑", "failed": "❌",
}

# ---- fonts (premium, real TTFs; lazy + cached; graceful fallback) ------------
_FONT_DIR = Path("C:/Windows/Fonts")
_FONT_FILES = {
    "regular": "segoeui.ttf", "medium": "seguisb.ttf", "semibold": "seguisb.ttf",
    "bold": "segoeuib.ttf", "mono": "CascadiaMono.ttf", "mono-bold": "consolab.ttf",
}
_FONT_CACHE: dict = {}


def font(size: int, weight: str = "regular"):
    """Load a cached PIL font (real TTF). ``weight`` in regular/medium/semibold/bold/mono/mono-bold.
    Falls back to Pillow's default if the TTF is unavailable (never raises)."""
    key = (size, weight)
    if key in _FONT_CACHE:
        return _FONT_CACHE[key]
    from PIL import ImageFont
    fnt = None
    fname = _FONT_FILES.get(weight, _FONT_FILES["regular"])
    try:
        fnt = ImageFont.truetype(str(_FONT_DIR / fname), size)
    except Exception:  # noqa: BLE001
        for alt in ("arialbd.ttf" if "bold" in weight else "arial.ttf", "consola.ttf"):
            try:
                fnt = ImageFont.truetype(str(_FONT_DIR / alt), size)
                break
            except Exception:  # noqa: BLE001
                continue
    if fnt is None:
        try:
            fnt = ImageFont.load_default(size=size)
        except Exception:  # noqa: BLE001
            fnt = ImageFont.load_default()
    _FONT_CACHE[key] = fnt
    return fnt


# ---- accessors --------------------------------------------------------------
def name() -> str:
    return config.COCKPIT_THEME if config.COCKPIT_THEME in PALETTES else "dark"


def pillowPalette() -> dict:
    p = dict(PALETTES[name()])
    p.setdefault("panel", p["surface"])   # back-compat aliases
    p.setdefault("grid", p["border"])
    return p


def ansiFrame() -> str:
    return ANSI_FRAME.get(name(), "36")


def ansiStatus(status) -> str:
    return ANSI_STATUS.get(status or "", "37")


def glyphs() -> tuple:
    return GLYPHS.get(name(), ("█", "░"))


def statusFill(status) -> tuple:
    pal = pillowPalette()
    return pal.get(_STATUS_KEY.get(status, "faint"), pal["muted"])


def accent(status) -> int:
    return config.STATUS_COLORS.get(status or "", config.BRAND_COLOR)


def phaseEmoji(phase) -> str:
    return PHASE_EMOJI.get(phase, "🛰")
