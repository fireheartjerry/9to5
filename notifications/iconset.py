"""Render professional icon PNGs (Segoe Fluent Icons) for use as Discord APPLICATION emojis.

Application emojis are app-owned (not guild emojis) -> they don't clutter the server's emoji
list and the bot can use them anywhere. Emojis can't recolor at display time, so each icon is
baked in a fixed semantic colour tuned for Discord's dark surface. Pure + testable (PNG bytes).
"""
from __future__ import annotations

import io

import config
from notifications import theme

LOG = config.getLogger("iconset")

# concept -> fixed display colour (RGB), tuned to read on Discord dark.
_COLOR = {
    "done": (63, 185, 80), "complete": (63, 185, 80), "verify": (63, 185, 80), "run": (63, 185, 80),
    "fail": (248, 81, 73), "blocked": (248, 81, 73), "abort": (201, 60, 55),
    "active": (88, 166, 255), "plan": (88, 166, 255), "architect": (88, 166, 255),
    "retry": (88, 166, 255), "info": (88, 166, 255),
    "pending": (139, 148, 158), "clock": (139, 148, 158), "model": (139, 148, 158),
    "effort": (139, 148, 158),
    "paused": (210, 153, 34), "warn": (210, 153, 34), "adversary": (219, 109, 40),
    "replan": (188, 140, 255), "brain": (188, 140, 255), "flag": (201, 209, 217),
    "reject": (248, 81, 73), "skip": (139, 148, 158), "resume": (63, 185, 80),
    "approve": (63, 185, 80),
}
DEFAULT_COLOR = (201, 209, 217)

# curated set uploaded as app emojis (name = nc_<concept>)
EMOJI_CONCEPTS = (
    "done", "fail", "active", "pending", "paused", "run", "warn", "blocked", "adversary",
    "plan", "architect", "verify", "replan", "retry", "abort", "info", "clock", "model",
    "effort", "brain", "complete", "flag", "reject", "skip", "resume", "approve",
)


def renderIcon(concept: str, size: int = 128) -> "bytes | None":
    """A square RGBA PNG of the concept's icon in its semantic colour, or None."""
    if not theme.iconChar(concept):
        return None
    try:
        from PIL import Image, ImageDraw
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        d = ImageDraw.Draw(img)
        color = _COLOR.get(concept, DEFAULT_COLOR) + (255,)
        f = theme.iconFont(int(size * 0.74))
        d.text((size // 2, size // 2 + 2), theme.iconChar(concept), font=f, fill=color, anchor="mm")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        LOG.warning("renderIcon(%s) failed", concept, exc_info=True)
        return None
