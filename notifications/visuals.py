"""Generative visuals -- Pillow-rendered cockpit imagery in the "Nightclaw Ops Console" design
language (GitHub-dark / Linear lineage): semantic color tokens, real type hierarchy (Segoe UI +
Cascadia Mono via theme.font), 4/8 spacing rhythm, gradient canvas + card depth, DRAWN vector
status glyphs (never emoji on the canvas), tabular mono figures for metrics.

Every entry point returns ``bytes`` (PNG/GIF) or ``None`` and NEVER raises, so a missing Pillow
or a render error can never break a run. Gated by ``config.VISUALS_ENABLED``.
"""
from __future__ import annotations

import io
from typing import Optional

import config
from notifications import theme

LOG = config.getLogger("visuals")


# ---- color helpers ----------------------------------------------------------
def _lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))


def _lighten(c, amt):
    return _lerp(c, (255, 255, 255), amt)


def _mix(fg, bg, alpha):
    """fg over bg at the given alpha (0..1) -- a flat approximation of translucency."""
    return _lerp(bg, fg, alpha)


def available() -> bool:
    if not config.VISUALS_ENABLED:
        return False
    try:
        import PIL  # noqa: F401
        return True
    except Exception:  # noqa: BLE001
        return False


def _pal() -> dict:
    return theme.pillowPalette()


def _font(size: int, weight: str = "regular"):
    return theme.font(size, weight)


# ---- drawing primitives -----------------------------------------------------
def _canvas(W: int, H: int, pal: dict):
    """A subtle vertical-gradient canvas (bg -> bg2), drawn line-by-line (fast)."""
    from PIL import Image, ImageDraw
    base = Image.new("RGB", (W, H), pal["bg"])
    d = ImageDraw.Draw(base)
    top, bot = pal["bg"], pal.get("bg2", pal["bg"])
    for y in range(H):
        d.line([(0, y), (W, y)], fill=_lerp(top, bot, y / max(H - 1, 1)))
    return base, d


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
    if len(lines) >= max_lines and words and draw.textlength(lines[-1], font=font) > max_w:
        while lines[-1] and draw.textlength(lines[-1] + "…", font=font) > max_w:
            lines[-1] = lines[-1][:-1]
        lines[-1] += "…"
    return lines or ["—"]


def _pill(draw, x: int, y: int, text: str, font, fg, bgcol, pad_x: int = 10, pad_y: int = 5) -> int:
    """Rounded chip with a translucent-ish fill; returns its total width."""
    tw = draw.textlength(text, font=font)
    h = (font.size if hasattr(font, "size") else 14) + pad_y * 2
    draw.rounded_rectangle([x, y, x + tw + pad_x * 2, y + h], radius=h // 2, fill=bgcol)
    draw.text((x + pad_x, y + pad_y), text, font=font, fill=fg)
    return int(tw + pad_x * 2)


def _progress(base, draw, box, pct: float, pal: dict) -> None:
    """Rounded track + clipped gradient fill (accent -> lighter) + thin top highlight."""
    from PIL import Image, ImageDraw
    x0, y0, x1, y1 = box
    h = y1 - y0
    r = h // 2
    draw.rounded_rectangle(box, radius=r, fill=pal["surface2"])
    fw = int((x1 - x0) * max(0.0, min(1.0, pct)))
    if fw >= h:
        grad = Image.new("RGB", (fw, h))
        gd = ImageDraw.Draw(grad)
        c1, c2 = pal["accent"], _lighten(pal["accent"], 0.30)
        for x in range(fw):
            gd.line([(x, 0), (x, h)], fill=_lerp(c1, c2, x / max(fw - 1, 1)))
        mask = Image.new("L", (fw, h), 0)
        ImageDraw.Draw(mask).rounded_rectangle([0, 0, fw - 1, h - 1], radius=r, fill=255)
        base.paste(grad, (x0, y0), mask)
        draw.line([(x0 + r, y0 + 1), (x0 + fw - r, y0 + 1)], fill=_lighten(pal["accent"], 0.5))


def _status_cells(draw, x: int, y: int, statuses: list, pal: dict,
                  cell: int = 22, gap: int = 7, per_row: int = 30) -> None:
    """A status heatmap: rounded cells coloured by subtask status (no emoji)."""
    for i, st in enumerate(statuses):
        r, c = divmod(i, per_row)
        cx = x + c * (cell + gap)
        cy = y + r * (cell + gap)
        col = theme.statusFill(st)
        draw.rounded_rectangle([cx, cy, cx + cell, cy + cell], radius=6, fill=col)
        if st in ("pending", "removed"):  # hollow-ish for not-yet-done
            draw.rounded_rectangle([cx, cy, cx + cell, cy + cell], radius=6,
                                   fill=pal["surface"], outline=col, width=2)


def _metrics(draw, x: int, y: int, width: int, items: list, pal: dict) -> None:
    """Evenly-spaced label/value columns with subtle dividers. items: [(label, value)]."""
    lbl_f = _font(11, "mono")
    val_f = _font(17, "mono-bold")
    n = max(len(items), 1)
    col_w = width // n
    for i, (label, value) in enumerate(items):
        cx = x + i * col_w
        if i:
            draw.line([(cx - 12, y + 2), (cx - 12, y + 40)], fill=pal["border"])
        draw.text((cx, y), label.upper(), font=lbl_f, fill=pal["muted"])
        draw.text((cx, y + 18), str(value), font=val_f, fill=pal["text"])


def _logo(draw, x: int, y: int, pal: dict) -> None:
    """A small accent claw-mark + NIGHTCLAW wordmark."""
    draw.rounded_rectangle([x, y, x + 26, y + 26], radius=7, fill=pal["accent"])
    draw.line([(x + 8, y + 7), (x + 18, y + 13), (x + 8, y + 19)], fill=pal["bg"], width=3, joint="curve")
    draw.text((x + 38, y - 1), "NIGHTCLAW", font=_font(20, "bold"), fill=pal["text"])
    draw.text((x + 38, y + 24), "OPS CONSOLE", font=_font(10, "mono"), fill=pal["muted"])


# ---- the cards --------------------------------------------------------------
def progressCard(state, *, phase: str = "executing", model: Optional[str] = None,
                 effort: str = "default") -> Optional[bytes]:
    if not available():
        return None
    try:
        pal = _pal()
        m = dict(state.meta)
        subs = [s for s in state.subtasks if s.get("status") != "removed"]
        done = sum(1 for s in subs if s.get("status") == "done")
        total = max(len(subs), 1)
        pct = done / total
        status = m.get("status", "?")
        acc = theme.statusFill("done") if status in ("done", "complete") else (
            theme.statusFill("failed") if status in ("failed", "blocked", "aborted") else pal["accent"])

        W, H = 900, 408
        img, d = _canvas(W, H, pal)
        M = 40
        # top accent strip (status-tinted)
        d.rectangle([0, 0, W, 4], fill=acc)

        _logo(d, M, 30, pal)
        # phase chip (right-aligned)
        chip_f = _font(12, "mono-bold")
        chip_txt = phase.upper()
        cw = d.textlength(chip_txt, font=chip_f) + 20 + 18
        d.ellipse([W - M - cw - 16, 41, W - M - cw - 6, 51], fill=acc)   # status dot
        _pill(d, int(W - M - cw), 36, chip_txt, chip_f, acc, _mix(acc, pal["surface"], 0.16))

        # goal
        for i, line in enumerate(_wrap(d, m.get("goal_raw", ""), _font(25, "semibold"), W - 2 * M, 2)):
            d.text((M, 96 + i * 33), line, font=_font(25, "semibold"), fill=pal["text"])

        # progress bar + readout
        by = 178
        _progress(img, d, [M, by, W - M - 150, by + 16], pct, pal)
        d.text((W - M - 132, by - 9), f"{int(round(pct * 100))}%", font=_font(28, "mono-bold"), fill=pal["text"])
        d.text((W - M - 132, by + 22), f"{done}/{total} done", font=_font(13, "mono"), fill=pal["muted"])

        # subtask heatmap
        d.text((M, 232), "SUBTASKS", font=_font(11, "mono"), fill=pal["muted"])
        _status_cells(d, M, 254, [s.get("status") for s in subs[:60]], pal)

        # divider + metrics footer
        d.line([(M, 318), (W - M, 318)], fill=pal["border"])
        advs = len(state.data.get("adversary_reviews", []))
        replans = sum(1 for n in state.data.get("notifications", []) if n.get("kind") == "replan")
        _metrics(d, M, 338, W - 2 * M, [
            ("model", (model or config.PRIMARY_MODEL).replace("claude-", "")),
            ("effort", effort), ("mode", m.get("control_mode", "watch")),
            ("replans", replans), ("adversary", advs),
        ], pal)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        LOG.warning("progressCard render failed", exc_info=True)
        return None


def burndownChart(state) -> Optional[bytes]:
    if not available():
        return None
    try:
        from PIL import ImageDraw  # noqa: F401
        pal = _pal()
        subs = [s for s in state.subtasks if s.get("status") != "removed"]
        order = ["done", "in_progress", "failed", "pending"]
        labels = {"done": "DONE", "in_progress": "ACTIVE", "failed": "FAILED", "pending": "PENDING"}
        counts = {k: sum(1 for s in subs if s.get("status") == k) for k in order}
        peak = max(max(counts.values()), 1)

        W, H = 620, 340
        img, d = _canvas(W, H, pal)
        d.rectangle([0, 0, W, 4], fill=pal["accent"])
        _logo(d, 36, 28, pal)
        d.text((36, 80), "SUBTASK STATUS", font=_font(11, "mono"), fill=pal["muted"])

        base_y, bar_w, gap, x0, span = H - 56, 96, 44, 56, H - 210
        for i in range(1, 5):                       # subtle gridlines
            gy = base_y - int(span * i / 4)
            d.line([(x0, gy), (W - 36, gy)], fill=pal["border"])
        for i, k in enumerate(order):
            x = x0 + i * (bar_w + gap)
            h = int(span * counts[k] / peak)
            col = theme.statusFill(k)
            d.rounded_rectangle([x, base_y - h, x + bar_w, base_y], radius=8, fill=col)
            d.text((x, base_y + 8), labels[k], font=_font(11, "mono"), fill=pal["muted"])
            vf = _font(20, "mono-bold")
            d.text((x + bar_w // 2 - d.textlength(str(counts[k]), font=vf) // 2, base_y - h - 26),
                   str(counts[k]), font=vf, fill=pal["text"])

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        LOG.warning("burndownChart render failed", exc_info=True)
        return None


_CHALLENGED = {"challenged", "rejected", "reject", "blocked", "fail"}


def duelCard(subtask_title: str, verdict: str, *, trust: Optional[float] = None) -> Optional[bytes]:
    if not available():
        return None
    try:
        pal = _pal()
        challenged = (verdict or "").lower().strip() in _CHALLENGED
        acc = pal["danger"] if challenged else pal["success"]
        W, H = 820, 300
        img, d = _canvas(W, H, pal)
        d.rectangle([0, 0, W, 4], fill=acc)
        _logo(d, 36, 26, pal)
        d.text((W - 36 - d.textlength("ADVERSARY REVIEW", font=_font(11, "mono")), 34),
               "ADVERSARY REVIEW", font=_font(11, "mono"), fill=pal["muted"])

        # two combatants + VS
        d.text((48, 96), "EXECUTOR", font=_font(26, "bold"), fill=pal["success"])
        d.text((48, 128), "the build", font=_font(13, "mono"), fill=pal["muted"])
        right = "ADVERSARY"
        rx = W - 48 - int(d.textlength(right, font=_font(26, "bold")))
        d.text((rx, 96), right, font=_font(26, "bold"), fill=pal["warning"])
        d.text((W - 48 - int(d.textlength("the critique", font=_font(13, "mono"))), 128),
               "the critique", font=_font(13, "mono"), fill=pal["muted"])
        vs = "VS"
        d.text((W // 2 - int(d.textlength(vs, font=_font(46, "bold")) / 2), 100), vs,
               font=_font(46, "bold"), fill=pal["faint"])

        # contested subtask
        for i, line in enumerate(_wrap(d, subtask_title, _font(16, "mono"), W - 96, 1)):
            d.text((48, 178), line, font=_font(16, "mono"), fill=pal["text"])

        # trust meter
        if trust is not None:
            d.text((48, 214), "TRUST", font=_font(11, "mono"), fill=pal["muted"])
            _progress(img, d, [110, 214, W - 240, 228], max(0.0, min(1.0, trust)), pal)
        # verdict chip (canvas stays emoji-free; a drawn dot marks it)
        chip = "CHALLENGED" if challenged else "APPROVED"
        cf = _font(15, "mono-bold")
        cw = int(d.textlength(chip, font=cf)) + 36 + 16
        _pill(d, W - 48 - cw, H - 56, chip, cf, acc, _mix(acc, pal["surface"], 0.18), pad_x=14, pad_y=7)
        # small marker dot before the chip
        d.ellipse([W - 48 - cw - 4, H - 50, W - 48 - cw + 6, H - 40], fill=acc)

        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        LOG.warning("duelCard render failed", exc_info=True)
        return None


# ---- animation --------------------------------------------------------------
def timelapseGif(frames: list, *, duration_ms: int = 700) -> Optional[bytes]:
    if not available() or not frames:
        return None
    try:
        from PIL import Image
        imgs = [Image.open(io.BytesIO(fb)).convert("P", palette=Image.ADAPTIVE) for fb in frames if fb]
        if not imgs:
            return None
        buf = io.BytesIO()
        imgs[0].save(buf, format="GIF", save_all=True, append_images=imgs[1:],
                     duration=duration_ms, loop=0)
        return buf.getvalue()
    except Exception:  # noqa: BLE001
        LOG.warning("timelapseGif render failed", exc_info=True)
        return None


class _Frame:
    def __init__(self, meta, subtasks, data):
        self.meta = meta
        self.subtasks = subtasks
        self.data = data


def runReplayGif(state, *, max_frames: int = 8) -> Optional[bytes]:
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
