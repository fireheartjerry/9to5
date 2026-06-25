"""Generative visuals -- Pillow-rendered cockpit imagery (progress cards, burndown
charts, end-of-run GIF timelapse). PURE-ish: every entry point returns ``bytes`` (a
PNG/GIF) or ``None`` and NEVER raises, so a missing Pillow or a render error can never
break a run. Wire the returned bytes into the cockpit via the shared multipart path
(``discord_bot.createComponentsV2(..., files=[(name, bytes, "image/png")])``).

Gated by ``config.VISUALS_ENABLED`` (auto-off when Pillow is unavailable).
"""
from __future__ import annotations

import io
from typing import Optional

import config
from notifications import theme

LOG = config.getLogger("visuals")

# --- theme palettes (bg, panel, text, muted, grid) -- keyed by COCKPIT_THEME ----
def available() -> bool:
    if not config.VISUALS_ENABLED:
        return False
    try:
        import PIL  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _theme() -> dict:
    return theme.pillowPalette()


def _rgb(value: int) -> tuple:
    return ((value >> 16) & 0xFF, (value >> 8) & 0xFF, value & 0xFF)


def _font(size: int):
    from PIL import ImageFont
    try:
        return ImageFont.load_default(size=size)   # Pillow >=10.1 honours size
    except Exception:  # noqa: BLE001
        return ImageFont.load_default()


def _wrap(draw, text: str, font, max_w: int, max_lines: int = 2) -> list:
    words = (text or "").split()
    lines, cur = [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=font) <= max_w:
            cur = trial
        else:
            if cur:
                lines.append(cur)
            cur = w
            if len(lines) >= max_lines:
                break
    if cur and len(lines) < max_lines:
        lines.append(cur)
    if len(lines) >= max_lines and words:
        lines[-1] = lines[-1][:60].rstrip() + "…"
    return lines or ["—"]


def progressCard(state, *, phase: str = "executing", model: Optional[str] = None,
                 effort: str = "default") -> Optional[bytes]:
    """A wide cockpit-hero PNG: phase, goal, progress bar, subtask grid, footer metrics.
    Returns PNG bytes, or None if visuals are unavailable / rendering fails."""
    if not available():
        return None
    try:
        from PIL import Image, ImageDraw

        th = _theme()
        m = dict(state.meta)
        subtasks = [s for s in state.subtasks if s.get("status") != "removed"]
        done = sum(1 for s in subtasks if s.get("status") == "done")
        total = max(len(subtasks), 1)
        pct = done / total
        accent = _rgb(config.STATUS_COLORS.get(m.get("status"), 0x5865F2))

        W, H = 840, 360
        img = Image.new("RGB", (W, H), th["bg"])
        d = ImageDraw.Draw(img)

        # header accent strip
        d.rectangle([0, 0, W, 8], fill=accent)
        d.text((28, 26), f"9TO5 · {phase}", font=_font(30), fill=th["text"])
        d.text((28, 64), f"status: {m.get('status', '?')}   ·   mode: {m.get('control_mode', 'watch')}",
               font=_font(18), fill=th["muted"])

        # goal (wrapped, up to 2 lines)
        for i, line in enumerate(_wrap(d, m.get("goal_raw", ""), _font(22), W - 56, 2)):
            d.text((28, 100 + i * 30), line, font=_font(22), fill=th["text"])

        # progress bar
        bx, by, bw, bh = 28, 178, W - 56, 30
        d.rounded_rectangle([bx, by, bx + bw, by + bh], radius=8, fill=th["panel"])
        if pct > 0:
            d.rounded_rectangle([bx, by, bx + int(bw * pct), by + bh], radius=8, fill=accent)
        d.text((bx + bw - 96, by + 4), f"{int(round(pct * 100))}%  {done}/{total}",
               font=_font(20), fill=th["text"])

        # subtask grid
        gx, gy, sq, gap = 28, 232, 22, 6
        per_row = (W - 56) // (sq + gap)
        for i, s in enumerate(subtasks[:per_row * 3]):
            r, c = divmod(i, per_row)
            x = gx + c * (sq + gap)
            y = gy + r * (sq + gap)
            d.rounded_rectangle([x, y, x + sq, y + sq], radius=4,
                                fill=theme.statusFill(s.get("status")))

        # footer metrics
        advs = len(state.data.get("adversary_reviews", []))
        replans = sum(1 for n in state.data.get("notifications", []) if n.get("kind") == "replan")
        d.text((28, H - 34),
               f"model {model or config.PRIMARY_MODEL}   ·   effort {effort}   ·   "
               f"replans {replans}   ·   adversary {advs}",
               font=_font(16), fill=th["muted"])

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001 -- visuals are best-effort; never break a run
        LOG.warning("progressCard render failed", exc_info=True)
        return None


def burndownChart(state) -> Optional[bytes]:
    """A simple status-breakdown bar chart (done/in_progress/failed/pending) as PNG."""
    if not available():
        return None
    try:
        from PIL import Image, ImageDraw

        th = _theme()
        subtasks = [s for s in state.subtasks if s.get("status") != "removed"]
        order = ["done", "in_progress", "failed", "pending"]
        counts = {k: sum(1 for s in subtasks if s.get("status") == k) for k in order}
        peak = max(max(counts.values()), 1)

        W, H = 560, 300
        img = Image.new("RGB", (W, H), th["bg"])
        d = ImageDraw.Draw(img)
        d.text((24, 18), "Subtask status", font=_font(22), fill=th["text"])
        base_y, bar_w, gap = H - 50, 90, 40
        for i, k in enumerate(order):
            x = 40 + i * (bar_w + gap)
            h = int((H - 110) * counts[k] / peak)
            d.rectangle([x, base_y - h, x + bar_w, base_y], fill=theme.statusFill(k))
            d.text((x, base_y + 6), k.replace("_", " "), font=_font(14), fill=th["muted"])
            d.text((x + bar_w // 2 - 6, base_y - h - 22), str(counts[k]), font=_font(18), fill=th["text"])

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        LOG.warning("burndownChart render failed", exc_info=True)
        return None


def timelapseGif(frames: list, *, duration_ms: int = 700) -> Optional[bytes]:
    """Stitch a list of PNG-byte frames into an animated GIF (end-of-run replay). Returns GIF bytes."""
    if not available() or not frames:
        return None
    try:
        from PIL import Image

        imgs = []
        for fb in frames:
            if fb:
                imgs.append(Image.open(io.BytesIO(fb)).convert("P", palette=Image.ADAPTIVE))
        if not imgs:
            return None
        buf = io.BytesIO()
        imgs[0].save(buf, format="GIF", save_all=True, append_images=imgs[1:],
                     duration=duration_ms, loop=0)
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        LOG.warning("timelapseGif render failed", exc_info=True)
        return None


_CHALLENGED = {"challenged", "rejected", "reject", "blocked", "fail"}


def duelCard(subtask_title: str, verdict: str, *, trust: Optional[float] = None) -> Optional[bytes]:
    """Render the Adversary 'duel' VS-card (Executor ⚙️ vs Adversary ⚔️ over a contested subtask,
    with a trust meter). Posted as the Adversary persona on a CHALLENGE. PNG bytes or None."""
    if not available():
        return None
    try:
        from PIL import Image, ImageDraw

        th = _theme()
        challenged = (verdict or "").lower().strip() in _CHALLENGED
        accent = (231, 76, 60) if challenged else (46, 204, 113)
        W, H = 800, 300
        img = Image.new("RGB", (W, H), th["bg"])
        d = ImageDraw.Draw(img)
        d.rectangle([0, 0, W, 8], fill=accent)
        d.text((40, 30), "⚙️ EXECUTOR", font=_font(32), fill=(46, 204, 113))
        right = "⚔️ ADVERSARY"
        d.text((W - 40 - int(d.textlength(right, font=_font(32))), 30), right, font=_font(32),
               fill=(230, 126, 34))
        vs = "VS"
        d.text((W // 2 - int(d.textlength(vs, font=_font(60)) / 2), H // 2 - 60), vs,
               font=_font(60), fill=th["text"])
        for i, line in enumerate(_wrap(d, subtask_title, _font(22), W - 80, 2)):
            d.text((40, 118 + i * 30), line, font=_font(22), fill=th["muted"])
        if trust is not None:
            tw = int(max(0.0, min(1.0, trust)) * (W - 80))
            d.rounded_rectangle([40, H - 92, W - 40, H - 74], radius=6, fill=th["panel"])
            if tw > 0:
                d.rounded_rectangle([40, H - 92, 40 + tw, H - 74], radius=6, fill=accent)
        d.text((40, H - 56), ("⚔️ CHALLENGED" if challenged else "✅ APPROVED"),
               font=_font(30), fill=accent)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        LOG.warning("duelCard render failed", exc_info=True)
        return None


class _Frame:
    def __init__(self, meta, subtasks, data):
        self.meta = meta
        self.subtasks = subtasks
        self.data = data


def runReplayGif(state, *, max_frames: int = 8) -> Optional[bytes]:
    """End-of-run cinematic: a GIF of the subtask grid igniting/clearing in order. Renders the
    progress card at progressively-higher done-counts and stitches the frames. GIF bytes or None."""
    if not available():
        return None
    try:
        subs = [s for s in state.subtasks if s.get("status") != "removed"]
        total = len(subs)
        if total == 0:
            return None
        steps = list(range(0, total + 1))
        if len(steps) > max_frames:
            steps = sorted({round(i * total / (max_frames - 1)) for i in range(max_frames)})
        frames = []
        for k in steps:
            fsubs = [dict(s, status=("done" if i < k else "pending")) for i, s in enumerate(subs)]
            frames.append(progressCard(_Frame(dict(state.meta), fsubs, state.data), phase="replay"))
        return timelapseGif([f for f in frames if f], duration_ms=450)
    except Exception:  # noqa: BLE001
        LOG.warning("runReplayGif failed", exc_info=True)
        return None
