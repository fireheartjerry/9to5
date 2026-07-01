# Discord Live Terminal Paginator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a persistent, paginated "Live Terminal" surface to the Nightclaw Discord bot where ◀ ▶ buttons switch between the live terminals of every sub-process (orchestrator, brain, browser, native, each Claude subtask), updating near-live within Discord rate limits.

**Architecture:** Extend the in-process `LiveEventBus` with lightweight lane bookkeeping (a lane = a well-known `sid`). A `TerminalSurface` manager owns one pinned message per run and runs an adaptive, edit-on-change, 429-backoff edit loop that renders the active lane via a pure `terminal_render` function. A persistent `TerminalView` provides ◀/⏸/Raw/▶/📷 buttons. Five one-line producer taps (via a shared `lane_feed.laneTap` helper) feed each layer into the bus.

**Tech Stack:** Python 3.11, `discord.py` (app commands + `ui.View`), stdlib `deque`/`threading`/`asyncio`, pytest.

**Reference spec:** `docs/superpowers/specs/2026-06-30-discord-live-terminal-paginator-design.md`

**Test rules:** Run tests with pytest, never bare unittest (local `.env` has live creds — see `.claude/rules/tests.md`). Use `python tools/dev.py check <file>` for focused runs.

---

## File Structure

**New files:**
- `notifications/lane_feed.py` — best-effort `laneTap(lane, line)` / `registerLane(lane, label)` wrappers over the bus.
- `notifications/terminal_render.py` — pure `render(...) -> str` (no I/O, never raises).
- `notifications/terminal_surface.py` — `EditThrottle` (pure) + `TerminalSurface` (manager) + `get_terminal_surface()` singleton accessor.
- `notifications/views_terminal.py` — persistent `TerminalView`.
- `tests/test_event_bus_lanes.py`, `tests/test_lane_feed.py`, `tests/test_terminal_render.py`, `tests/test_terminal_surface.py`, `tests/test_views_terminal.py`.

**Modified files:**
- `notifications/event_bus.py` — lane bookkeeping.
- `notifications/bot/core.py` — register `TerminalView` as a persistent view.
- `llm_io.py`, `platform_core/orchestration/run_loop_mixin.py`, `platform_core/orchestration/run_phase_mixin.py`, `agents/browser_executor.py`, `agents/native_executor.py` — one `laneTap` each.
- The orchestrator path that starts/stops `DiscordDashboard` — also start/stop `TerminalSurface`.

---

## Task 1: Bus lane bookkeeping

**Files:**
- Modify: `notifications/event_bus.py`
- Test: `tests/test_event_bus_lanes.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_event_bus_lanes.py
from notifications.event_bus import LiveEventBus


def test_lanes_report_order_count_and_label():
    bus = LiveEventBus()
    bus.register_lane("brain", "Ollama brain")
    bus.emit_raw("orchestrator", "planning")
    bus.emit_raw("brain", "prompt >> hi")
    bus.emit_raw("brain", "response << ok")

    lanes = bus.lanes()
    ids = [l["id"] for l in lanes]
    assert ids == ["brain", "orchestrator"]  # register_lane created 'brain' first

    brain = next(l for l in lanes if l["id"] == "brain")
    assert brain["label"] == "Ollama brain"
    assert brain["line_count"] == 2
    assert brain["idle_s"] >= 0.0


def test_lanes_empty_when_no_activity():
    assert LiveEventBus().lanes() == []


def test_emit_raw_still_feeds_raw_history():
    bus = LiveEventBus()
    bus.emit_raw("st-001", "hello")
    assert [r["line"] for r in bus.raw_history("st-001")] == ["hello"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_event_bus_lanes.py -v`
Expected: FAIL — `AttributeError: 'LiveEventBus' object has no attribute 'register_lane'`.

- [ ] **Step 3: Write minimal implementation**

In `notifications/event_bus.py`, add a `LaneMeta` dataclass after `RawLine`:

```python
@dataclass
class LaneMeta:
    """Bookkeeping for one lane (a well-known sid: 'brain', 'orchestrator', 'st-001'...)."""
    id: str
    label: str = ""
    last_ts: float = field(default_factory=time.monotonic)
    line_count: int = 0
```

In `LiveEventBus.__init__`, add:

```python
        self._lanes: dict[str, LaneMeta] = {}
```

In `emit_raw`, inside the `with self._lock:` block, after appending to the ring, add:

```python
            meta = self._lanes.get(sid)
            if meta is None:
                meta = self._lanes[sid] = LaneMeta(id=sid)
            meta.last_ts = rl.ts
            meta.line_count += 1
```

Add two methods after `raw_history`:

```python
    def register_lane(self, sid: str, label: str = "") -> None:
        """Pre-create a lane (or set its friendly label) before its first line."""
        with self._lock:
            meta = self._lanes.get(sid)
            if meta is None:
                self._lanes[sid] = LaneMeta(id=sid, label=label)
            elif label:
                meta.label = label

    def lanes(self) -> list[dict[str, Any]]:
        """Ordered (first-activity) lane snapshots for the paginator."""
        now = time.monotonic()
        with self._lock:
            metas = list(self._lanes.values())
        return [{"id": m.id, "label": m.label, "last_ts": m.last_ts,
                 "line_count": m.line_count, "idle_s": max(0.0, now - m.last_ts)}
                for m in metas]
```

Update the module docstring `EXPORTS:` to add `LaneMeta` and the two methods.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_event_bus_lanes.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add notifications/event_bus.py tests/test_event_bus_lanes.py
git commit -m "feat(event-bus): lane bookkeeping for terminal paginator"
```

---

## Task 2: Best-effort lane tap helper

**Files:**
- Create: `notifications/lane_feed.py`
- Test: `tests/test_lane_feed.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_lane_feed.py
from notifications import lane_feed
from notifications.event_bus import get_bus, reset_bus


def setup_function(_):
    reset_bus()


def test_lane_tap_writes_to_bus():
    lane_feed.laneTap("brain", "hello brain")
    assert [r["line"] for r in get_bus().raw_history("brain")] == ["hello brain"]


def test_register_lane_sets_label():
    lane_feed.registerLane("st-002", "authcache refactor")
    assert get_bus().lanes()[0]["label"] == "authcache refactor"


def test_lane_tap_is_best_effort(monkeypatch):
    def boom():
        raise RuntimeError("bus down")
    monkeypatch.setattr(lane_feed, "get_bus", boom)
    # Must NOT raise — a bus hiccup can never break a producing layer.
    lane_feed.laneTap("brain", "x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_lane_feed.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'notifications.lane_feed'`.

- [ ] **Step 3: Write minimal implementation**

```python
# notifications/lane_feed.py
"""Best-effort producer taps that feed a layer's output into the LiveEventBus as a lane.

Every 9to5 layer (brain, orchestrator, browser, native, subtasks) calls ``laneTap`` to
publish one terminal line. Wrapped so a bus hiccup can NEVER break the producing layer.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  laneTap(lane: str, line: str) -> None  -- Publish one raw terminal line for ``lane`` (best-effort).
  registerLane(lane: str, label: str) -> None  -- Set a friendly label for ``lane`` (best-effort).
DEPENDS-ON: notifications.event_bus
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_lane_feed.py
"""
from __future__ import annotations

from notifications.event_bus import get_bus


def laneTap(lane: str, line: str) -> None:
    """Publish one raw terminal line for ``lane``. Never raises."""
    try:
        get_bus().emit_raw(lane, str(line))
    except Exception:  # noqa: BLE001 -- a bus hiccup must never break a producing layer
        pass


def registerLane(lane: str, label: str = "") -> None:
    """Set a friendly label for ``lane`` before its first line. Never raises."""
    try:
        get_bus().register_lane(lane, label)
    except Exception:  # noqa: BLE001
        pass
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_lane_feed.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Commit**

```bash
git add notifications/lane_feed.py tests/test_lane_feed.py
git commit -m "feat(lane-feed): best-effort lane tap helper"
```

---

## Task 3: Pure terminal renderer

**Files:**
- Create: `notifications/terminal_render.py`
- Test: `tests/test_terminal_render.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_terminal_render.py
from notifications.terminal_render import render

META = {"label": "authcache", "idle_s": 0.5, "line_count": 3, "elapsed_s": 41}


def test_render_contains_header_and_tail():
    body = render("st-002", ["a", "b", "c"], META, page=1, page_count=4,
                  mode="summary", frozen=False)
    assert "1/4" in body
    assert "authcache" in body
    assert "c" in body            # newest line present
    assert body.count("```") == 2  # exactly one fenced block


def test_render_caps_total_length():
    huge = [f"line-{i} " + "x" * 500 for i in range(400)]
    body = render("brain", huge, META, page=1, page_count=1, mode="raw", frozen=False)
    assert len(body) <= 1900
    assert "line-399" in body      # tail kept, head dropped


def test_render_truncates_long_lines():
    body = render("brain", ["z" * 999], META, page=1, page_count=1,
                  mode="raw", frozen=False)
    assert len(body) <= 1900
    assert "z" in body


def test_render_marks_frozen_and_empty():
    frozen = render("brain", [], META, page=1, page_count=1, mode="summary", frozen=True)
    assert "FROZEN" in frozen.upper()
    empty = render("brain", [], META, page=1, page_count=1, mode="summary", frozen=False)
    assert "```" in empty            # still a valid block, no crash


def test_render_never_raises_on_bad_input():
    # None lines / weird meta must degrade to an offline frame, not raise.
    body = render("x", None, {}, page=1, page_count=1, mode="summary", frozen=False)
    assert isinstance(body, str) and body


def test_control_rows_have_stable_ids():
    from notifications.terminal_render import TERM_CUSTOM_IDS, terminalControlRows
    assert TERM_CUSTOM_IDS == {
        "prev": "term_prev", "freeze": "term_freeze", "raw": "term_raw",
        "next": "term_next", "snap": "term_snap",
    }
    rows = terminalControlRows()
    # Discord action rows: {"type":1,"components":[{"type":2,...,"custom_id":...}]}
    cids = {c["custom_id"] for row in rows for c in row["components"]}
    assert set(TERM_CUSTOM_IDS.values()) <= cids
    assert all(row["type"] == 1 for row in rows)
    assert all(len(row["components"]) <= 5 for row in rows)  # Discord max 5/row
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_terminal_render.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'notifications.terminal_render'`.

- [ ] **Step 3: Write minimal implementation**

```python
# notifications/terminal_render.py
"""Pure renderer for the Discord Live Terminal surface. No I/O; never raises.

Turns a lane's tail of terminal lines into a Discord message body (fenced block +
header/footer) that fits Discord's 2,000-char content limit.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  render(lane_id, lines, meta, *, page, page_count, mode, frozen, width=64) -> str  -- Message body for one lane.
DEPENDS-ON: (stdlib only)
SIDE-EFFECTS: none
RUN/TEST: python -m pytest tests/test_terminal_render.py
"""
from __future__ import annotations

import re
from typing import Any, Optional

_MAX_BODY = 1900        # safe under Discord's 2000-char content cap
_MAX_LINE = 110         # per-line hard truncation
_ANSI = re.compile(r"\x1b\[[0-9;]*m")


def _fmt_elapsed(secs: Any) -> str:
    try:
        s = int(secs)
    except (TypeError, ValueError):
        return "—"
    if s < 0:
        s = 0
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h {m}m"
    if m:
        return f"{m}m {sec}s"
    return f"{sec}s"


def _clean(line: Any) -> str:
    text = _ANSI.sub("", str(line)).rstrip("\n").replace("`", "ˋ")
    return text[:_MAX_LINE]


def render(lane_id: str, lines: Optional[list], meta: Optional[dict], *,
           page: int, page_count: int, mode: str, frozen: bool, width: int = 64) -> str:
    """Return the Discord message body for one lane. Best-effort: any failure yields a
    minimal 'terminal offline' frame rather than raising."""
    try:
        meta = meta or {}
        label = str(meta.get("label") or lane_id)[:40]
        idle = float(meta.get("idle_s") or 0.0)
        pulse = "running" if idle < 5.0 else f"idle {int(idle)}s"
        elapsed = _fmt_elapsed(meta.get("elapsed_s"))
        badge = "RAW" if mode == "raw" else "SUMMARY"
        state = " · ⏸FROZEN" if frozen else ""
        header = (f"🖥 LIVE TERMINAL   ◀ {page}/{page_count} ▶   "
                  f"{lane_id} · {label} · {pulse} · {elapsed}")
        footer = (f"[{badge}]{state} · {meta.get('line_count', 0)} lines · "
                  f"📷 snapshot to keep")

        cleaned = [_clean(x) for x in (lines or [])]
        # Fill the block from newest → oldest until we hit the char budget.
        budget = _MAX_BODY - len(header) - len(footer) - 12  # 12 = fences + newlines
        picked: list[str] = []
        used = 0
        for line in reversed(cleaned):
            cost = len(line) + 1
            if used + cost > budget:
                break
            picked.append(line)
            used += cost
        picked.reverse()
        block = "\n".join(picked) if picked else "(no output yet)"
        return f"{header}\n```\n{block}\n```\n{footer}"
    except Exception:  # noqa: BLE001 -- renderer is total
        return f"🖥 LIVE TERMINAL — offline\n```\n(render error for {lane_id})\n```"


# Stable button ids shared by the persistent view AND the raw REST component rows.
TERM_CUSTOM_IDS = {
    "prev": "term_prev", "freeze": "term_freeze", "raw": "term_raw",
    "next": "term_next", "snap": "term_snap",
}


def terminalControlRows() -> list:
    """Raw Discord action-row dicts for a REST-created/edited message. custom_ids match
    the persistent TerminalView so the registered view routes the interactions."""
    def _btn(style: int, cid: str, *, label: str = "", emoji: str = "") -> dict:
        b: dict = {"type": 2, "style": style, "custom_id": cid}
        if label:
            b["label"] = label
        if emoji:
            b["emoji"] = {"name": emoji}
        return b

    return [{"type": 1, "components": [
        _btn(2, TERM_CUSTOM_IDS["prev"], emoji="◀"),
        _btn(2, TERM_CUSTOM_IDS["freeze"], emoji="⏸"),
        _btn(1, TERM_CUSTOM_IDS["raw"], label="Raw"),
        _btn(2, TERM_CUSTOM_IDS["next"], emoji="▶"),
        _btn(3, TERM_CUSTOM_IDS["snap"], emoji="📷"),
    ]}]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_terminal_render.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Commit**

```bash
git add notifications/terminal_render.py tests/test_terminal_render.py
git commit -m "feat(terminal-render): pure Discord terminal body renderer"
```

---

## Task 4: EditThrottle + page-clamp (pure surface logic)

**Files:**
- Create: `notifications/terminal_surface.py` (partial — pure logic only this task)
- Test: `tests/test_terminal_surface.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_terminal_surface.py
from notifications.terminal_surface import EditThrottle, clamp_page


def test_clamp_page_bounds():
    assert clamp_page(5, 4) == 3
    assert clamp_page(-2, 4) == 0
    assert clamp_page(0, 0) == 0    # no lanes


def test_throttle_blocks_when_frozen_or_unchanged():
    t = EditThrottle(floor=1.2)
    assert t.should_edit(now=100.0, changed=True, frozen=False) is True
    assert t.should_edit(now=100.0, changed=False, frozen=False) is False
    assert t.should_edit(now=100.0, changed=True, frozen=True) is False


def test_throttle_enforces_floor_after_success():
    t = EditThrottle(floor=1.2)
    assert t.should_edit(now=100.0, changed=True, frozen=False) is True
    t.note_success(now=100.0)
    assert t.should_edit(now=100.5, changed=True, frozen=False) is False  # within floor
    assert t.should_edit(now=101.3, changed=True, frozen=False) is True   # past floor


def test_throttle_backs_off_on_429_and_decays():
    t = EditThrottle(floor=1.2, cap=10.0)
    t.note_429(now=100.0, retry_after=2.0)
    assert t.floor == 2.4                       # doubled
    assert t.should_edit(now=101.9, changed=True, frozen=False) is False  # retry_after honored
    assert t.should_edit(now=102.1, changed=True, frozen=False) is True
    t.note_success(now=102.1)
    assert t.floor < 2.4                         # decays back toward base
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_terminal_surface.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'notifications.terminal_surface'`.

- [ ] **Step 3: Write minimal implementation**

```python
# notifications/terminal_surface.py
"""Live Terminal surface manager for Discord. Owns one pinned message per run and an
adaptive, edit-on-change, 429-backoff edit loop that renders the active lane.

This module has two parts:
  * EditThrottle + clamp_page -- pure, unit-tested rate-limit/navigation math.
  * TerminalSurface -- the I/O manager (added in a later task).

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  EditThrottle  -- Adaptive edit-rate governor (floor + 429 backoff + decay).
  clamp_page(idx: int, count: int) -> int  -- Bound a page index to [0, count-1].
DEPENDS-ON: (stdlib only, this task)
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_terminal_surface.py
"""
from __future__ import annotations


def clamp_page(idx: int, count: int) -> int:
    """Bound a page index to a valid lane slot; 0 when there are no lanes."""
    if count <= 0:
        return 0
    return max(0, min(idx, count - 1))


class EditThrottle:
    """Governs how often the surface may edit its message. Edit only when content
    changed, not frozen, and at least ``floor`` seconds since the last edit. A 429
    doubles the floor (capped) and honors Retry-After; each success decays it back."""

    def __init__(self, floor: float = 1.2, cap: float = 10.0) -> None:
        self._base = floor
        self.floor = floor
        self._cap = cap
        self._next_ok = float("-inf")   # earliest monotonic time an edit is allowed

    def should_edit(self, now: float, changed: bool, frozen: bool) -> bool:
        if frozen or not changed:
            return False
        return now >= self._next_ok

    def note_success(self, now: float) -> None:
        self.floor = max(self._base, self.floor * 0.5)
        self._next_ok = now + self.floor

    def note_429(self, now: float, retry_after: float) -> None:
        self.floor = min(self._cap, self.floor * 2)
        self._next_ok = now + max(retry_after, self.floor)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_terminal_surface.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Commit**

```bash
git add notifications/terminal_surface.py tests/test_terminal_surface.py
git commit -m "feat(terminal-surface): pure EditThrottle + page clamp"
```

---

## Task 5: TerminalSurface manager (I/O + nav + singleton)

**Files:**
- Modify: `notifications/terminal_surface.py`
- Test: `tests/test_terminal_surface.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_terminal_surface.py`:

```python
import notifications.terminal_surface as ts
from notifications.event_bus import get_bus, reset_bus


class _FakeDiscord:
    """Mirrors the notifications.discord_bot facade contract used by the surface."""
    def __init__(self):
        self.edits = []
        self.created = 0

    def noticeEmbed(self, body, title=""):
        return {"description": body, "title": title}

    def createMessage(self, embed, content=None, components=None):
        self.created += 1
        return "msg-1"

    def pinMessage(self, mid):
        return True

    def editMessageResult(self, mid, embed, content=None, components=None):
        self.edits.append((mid, embed))
        return "ok"   # facade contract: 'ok' | 'not_found' | 'transient'


def _fresh_surface(monkeypatch):
    reset_bus()
    fake = _FakeDiscord()
    monkeypatch.setattr(ts, "discord", fake, raising=False)
    s = ts.TerminalSurface()
    return s, fake


def test_nav_wraps_and_clamps_to_live_lanes(monkeypatch):
    s, _ = _fresh_surface(monkeypatch)
    get_bus().emit_raw("orchestrator", "a")
    get_bus().emit_raw("brain", "b")          # 2 lanes now
    assert s.page_idx == 0
    s.next(); assert s.page_idx == 1
    s.next(); assert s.page_idx == 1          # clamped at last lane
    s.prev(); assert s.page_idx == 0


def test_toggle_raw_and_freeze(monkeypatch):
    s, _ = _fresh_surface(monkeypatch)
    assert s.mode == "summary"
    s.toggle_raw(); assert s.mode == "raw"
    assert s.frozen is False
    s.toggle_freeze(); assert s.frozen is True


def test_render_once_edits_only_on_change(monkeypatch):
    s, fake = _fresh_surface(monkeypatch)
    s.message_id = "msg-1"
    get_bus().emit_raw("brain", "hello")
    s.render_once(now=100.0)
    n = len(fake.edits)
    assert n == 1
    s.render_once(now=101.5)                  # nothing changed -> no new edit
    assert len(fake.edits) == n


def test_snapshot_returns_current_body(monkeypatch):
    s, _ = _fresh_surface(monkeypatch)
    get_bus().emit_raw("brain", "snap-me")
    body = s.snapshot()
    assert "snap-me" in body


def test_singleton_accessor(monkeypatch):
    s, _ = _fresh_surface(monkeypatch)
    ts.set_terminal_surface(s)
    assert ts.get_terminal_surface() is s
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_terminal_surface.py -v`
Expected: FAIL — `AttributeError: module 'notifications.terminal_surface' has no attribute 'TerminalSurface'`.

- [ ] **Step 3: Write minimal implementation**

Append to `notifications/terminal_surface.py` (and update the docstring `EXPORTS:`
to list `TerminalSurface`, `get_terminal_surface`, `set_terminal_surface`):

```python
import threading
import time
from typing import Optional

import config
from notifications import discord_bot as discord   # facade: noticeEmbed/createMessage/editMessageResult/pinMessage
from notifications.event_bus import get_bus
from notifications.terminal_render import render, terminalControlRows

LOG = config.getLogger("terminal_surface")

_TITLE = "🖥 Live Terminal"


class TerminalSurface:
    """Owns one pinned Live Terminal message per run + the adaptive edit loop."""

    def __init__(self) -> None:
        self.message_id: Optional[str] = None
        self.page_idx = 0
        self.mode = "summary"          # 'summary' | 'raw'
        self.frozen = False
        self._started_at = time.monotonic()
        self._throttle = EditThrottle()
        self._last_body: Optional[str] = None
        self._recreated = False
        self._lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._task = None              # asyncio.Task, set by start()

    # ---- data ----------------------------------------------------------
    def _lanes(self) -> list:
        return get_bus().lanes()

    def _active_lane(self):
        lanes = self._lanes()
        if not lanes:
            return None, []
        self.page_idx = clamp_page(self.page_idx, len(lanes))
        lane = lanes[self.page_idx]
        raw = get_bus().raw_history(lane["id"], last_n=200)
        lines = [r["line"] for r in raw]
        return lane, lines

    def _body(self) -> str:
        lane, lines = self._active_lane()
        lanes = self._lanes()
        if lane is None:
            return render("—", [], {"label": "no live processes"}, page=0, page_count=0,
                          mode=self.mode, frozen=self.frozen)
        meta = dict(lane)
        meta["elapsed_s"] = time.monotonic() - self._started_at
        return render(lane["id"], lines, meta, page=self.page_idx + 1,
                      page_count=len(lanes), mode=self.mode, frozen=self.frozen)

    # ---- navigation (called by the view) -------------------------------
    def next(self) -> None:
        with self._lock:
            self.page_idx = clamp_page(self.page_idx + 1, max(1, len(self._lanes())))

    def prev(self) -> None:
        with self._lock:
            self.page_idx = clamp_page(self.page_idx - 1, max(1, len(self._lanes())))

    def toggle_raw(self) -> None:
        self.mode = "raw" if self.mode == "summary" else "summary"

    def toggle_freeze(self) -> None:
        self.frozen = not self.frozen

    def snapshot(self) -> str:
        return self._body()

    # ---- rendering / editing -------------------------------------------
    def render_once(self, now: Optional[float] = None) -> None:
        """Render + edit the message iff changed and the throttle allows. Never raises.
        Facade edit contract: 'ok' | 'not_found' | 'transient' (transient -> back off,
        never recreate; only a genuine 404 recreates, once)."""
        now = time.monotonic() if now is None else now
        try:
            body = self._body()
            changed = body != self._last_body
            if not self._throttle.should_edit(now, changed, self.frozen):
                return
            if not self.message_id:
                return
            embed = discord.noticeEmbed(body, title=_TITLE)
            with self._send_lock:
                res = discord.editMessageResult(self.message_id, embed,
                                                components=terminalControlRows())
            if res == "ok":
                self._last_body = body
                self._throttle.note_success(now)
            elif res == "transient":
                self._throttle.note_429(now, retry_after=1.0)   # back off on 429/5xx/timeout
            elif res == "not_found" and not self._recreated:
                self._recreated = True
                self._recreate()
        except Exception:  # noqa: BLE001 -- the loop must never die
            LOG.debug("terminal render_once failed", exc_info=True)

    def _recreate(self) -> None:
        with self._send_lock:
            embed = discord.noticeEmbed(self._body(), title=_TITLE)
            self.message_id = discord.createMessage(embed, components=terminalControlRows())
            if self.message_id:
                discord.pinMessage(self.message_id)

    # ---- lifecycle -----------------------------------------------------
    def start(self) -> None:
        """Create + pin the message and launch the async edit loop. Best-effort."""
        try:
            with self._send_lock:
                embed = discord.noticeEmbed(self._body(), title=_TITLE)
                self.message_id = discord.createMessage(embed, components=terminalControlRows())
                if self.message_id:
                    discord.pinMessage(self.message_id)
            import asyncio
            self._task = asyncio.get_event_loop().create_task(self._loop())
        except Exception:  # noqa: BLE001
            LOG.warning("terminal surface start failed", exc_info=True)

    async def _loop(self) -> None:
        import asyncio
        while True:
            self.render_once()
            await asyncio.sleep(0.4)   # the throttle floor, not this tick, governs edits

    def finalize(self) -> None:
        """Freeze the surface at run end (leave the message as a static record)."""
        self.frozen = True
        task = self._task
        if task is not None:
            task.cancel()


_SURFACE: Optional[TerminalSurface] = None
_SURFACE_LOCK = threading.Lock()


def get_terminal_surface() -> Optional[TerminalSurface]:
    return _SURFACE


def set_terminal_surface(surface: Optional[TerminalSurface]) -> None:
    global _SURFACE
    with _SURFACE_LOCK:
        _SURFACE = surface
```

> **Verified facade contract (notifications/discord_bot, aliased `discord`):**
> `createMessage(embed, content=None, components=None) -> Optional[str]`,
> `editMessageResult(message_id, embed, content=None, components=None) -> "ok"|"not_found"|"transient"`,
> `pinMessage(message_id) -> bool`, `noticeEmbed(body, title="") -> dict`. The surface
> wraps the rendered string in an embed and attaches `terminalControlRows()` so buttons
> appear on the REST-created message; `transient` triggers throttle backoff (never a
> recreate). Do NOT change the facade's public contract.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_terminal_surface.py -v`
Expected: PASS (9 passed — 4 from Task 4 + 5 new).

- [ ] **Step 5: Commit**

```bash
git add notifications/terminal_surface.py tests/test_terminal_surface.py
git commit -m "feat(terminal-surface): manager, nav, edit loop, singleton"
```

---

## Task 6: Persistent TerminalView

**Files:**
- Create: `notifications/views_terminal.py`
- Test: `tests/test_views_terminal.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_views_terminal.py
from notifications.terminal_render import TERM_CUSTOM_IDS
from notifications.views_terminal import TerminalView


def test_view_is_persistent_and_matches_shared_ids():
    v = TerminalView()
    assert v.timeout is None
    ids = {c.custom_id for c in v.children if hasattr(c, "custom_id")}
    assert set(TERM_CUSTOM_IDS.values()) <= ids   # ids come from terminal_render (single source)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_views_terminal.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'notifications.views_terminal'`.

- [ ] **Step 3: Write minimal implementation**

```python
# notifications/views_terminal.py
"""Persistent Discord view for the Live Terminal surface: ◀ Prev · ⏸ Freeze · Raw ·
Next ▶ · 📷 Snapshot. timeout=None + stable custom_ids so it survives multi-hour runs
and bot restarts. Registered in notifications/bot/core.py.

@AI-MAP v1  (generated by tools/repo_map.py -- edit SIDE-EFFECTS only, then regenerate)
EXPORTS:
  TerminalView  -- Persistent paginator view bound to the process-global TerminalSurface.
DEPENDS-ON: discord, notifications.commands, notifications.terminal_render, notifications.terminal_surface
SIDE-EFFECTS: unannotated
RUN/TEST: python -m pytest tests/test_views_terminal.py
"""
from __future__ import annotations

import discord

from notifications import commands
from notifications.terminal_render import TERM_CUSTOM_IDS   # single source of the ids
from notifications.terminal_surface import get_terminal_surface


async def _ack_and_repaint(interaction: "discord.Interaction") -> None:
    """Ack the button, then force a throttled repaint via the surface's own REST edit
    (keeps the embed + component rows intact — never blanks them with edit_message)."""
    surface = get_terminal_surface()
    if surface is None:
        await interaction.response.send_message("No live run.", ephemeral=True)
        return
    await interaction.response.defer()
    surface.render_once()


class TerminalView(discord.ui.View):
    def __init__(self) -> None:
        super().__init__(timeout=None)

    async def _guard(self, interaction) -> bool:
        if not commands.isAuthorized(interaction.user.id):
            await interaction.response.send_message("Not authorized.", ephemeral=True)
            return False
        return True

    @discord.ui.button(emoji="◀", style=discord.ButtonStyle.secondary, custom_id="term_prev")
    async def prev(self, interaction, _button):  # noqa: ANN001
        if not await self._guard(interaction):
            return
        s = get_terminal_surface()
        if s:
            s.prev()
        await _ack_and_repaint(interaction)

    @discord.ui.button(emoji="⏸", style=discord.ButtonStyle.secondary, custom_id="term_freeze")
    async def freeze(self, interaction, _button):  # noqa: ANN001
        if not await self._guard(interaction):
            return
        s = get_terminal_surface()
        if s:
            s.toggle_freeze()
        await _ack_and_repaint(interaction)

    @discord.ui.button(label="Raw", style=discord.ButtonStyle.primary, custom_id="term_raw")
    async def raw(self, interaction, _button):  # noqa: ANN001
        if not await self._guard(interaction):
            return
        s = get_terminal_surface()
        if s:
            s.toggle_raw()
        await _ack_and_repaint(interaction)

    @discord.ui.button(emoji="▶", style=discord.ButtonStyle.secondary, custom_id="term_next")
    async def next(self, interaction, _button):  # noqa: ANN001
        if not await self._guard(interaction):
            return
        s = get_terminal_surface()
        if s:
            s.next()
        await _ack_and_repaint(interaction)

    @discord.ui.button(emoji="📷", style=discord.ButtonStyle.success, custom_id="term_snap")
    async def snap(self, interaction, _button):  # noqa: ANN001
        s = get_terminal_surface()
        if s is None:
            await interaction.response.send_message("No live run.", ephemeral=True)
            return
        from notifications import discord_bot as discord_facade
        await interaction.response.send_message(
            embed=discord_facade.noticeEmbed(s.snapshot(), title="🖥 Live Terminal (snapshot)"),
            ephemeral=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_views_terminal.py -v`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add notifications/views_terminal.py tests/test_views_terminal.py
git commit -m "feat(views-terminal): persistent Live Terminal paginator view"
```

---

## Task 7: Register the view on the bot

**Files:**
- Modify: `notifications/bot/core.py` (near the other `bot.add_view(...)` calls, ~line 83-85)

- [ ] **Step 1: Add the registration**

In the function that registers persistent views (where `bot.add_view(views.ControlPanelView())` etc. live), add:

```python
    from notifications.views_terminal import TerminalView
    bot.add_view(TerminalView())              # persistent: matches term_* anywhere
```

- [ ] **Step 2: Verify the bot imports cleanly**

Run: `python -c "import notifications.bot.core"`
Expected: no output, exit 0.

- [ ] **Step 3: Verify view registration does not crash view setup**

Run: `python -m pytest tests/test_views_terminal.py tests/test_bot_cogs.py -v`
Expected: PASS (existing bot-cog tests still green).

- [ ] **Step 4: Commit**

```bash
git add notifications/bot/core.py
git commit -m "feat(bot): register persistent TerminalView"
```

---

## Task 8: Producer taps (brain, orchestrator, browser, native)

**Files:**
- Modify: `llm_io.py`, `platform_core/orchestration/run_loop_mixin.py`,
  `platform_core/orchestration/run_phase_mixin.py`, `agents/browser_executor.py`,
  `agents/native_executor.py`
- Test: `tests/test_terminal_taps.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_terminal_taps.py
from notifications.event_bus import get_bus, reset_bus
from notifications import lane_feed


def setup_function(_):
    reset_bus()


def test_brain_tap_publishes_to_brain_lane():
    # llm_io must route a completed call through lane_feed.laneTap("brain", ...).
    import llm_io
    assert hasattr(llm_io, "_tap_brain"), "llm_io needs a _tap_brain helper calling laneTap"
    llm_io._tap_brain("prompt→ hi", "response← ok")
    lines = [r["line"] for r in get_bus().raw_history("brain")]
    assert any("ok" in x for x in lines)


def test_lane_feed_tap_is_isolated_from_bus_errors(monkeypatch):
    # A raising bus must not propagate out of laneTap (covers every producer).
    monkeypatch.setattr(lane_feed, "get_bus", lambda: (_ for _ in ()).throw(RuntimeError()))
    lane_feed.laneTap("orchestrator", "x")   # must not raise
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_terminal_taps.py -v`
Expected: FAIL — `AssertionError: llm_io needs a _tap_brain helper calling laneTap`.

- [ ] **Step 3: Add the taps**

**`llm_io.py`** — add a small helper and call it where a brain call completes (find the
function that returns the Ollama completion; grep for `chat`/`generate`/`completion`):

```python
def _tap_brain(prompt_summary: str, response_summary: str) -> None:
    from notifications.lane_feed import laneTap
    laneTap("brain", f"→ {str(prompt_summary)[:90]}")
    laneTap("brain", f"← {str(response_summary)[:90]}")
```

Call `_tap_brain(<prompt preview>, <response preview>)` immediately after a successful
completion is produced.

**`platform_core/orchestration/run_phase_mixin.py`** — at each phase transition (grep for
where phase/status is logged, e.g. `LOG.info` on plan/replan/execute/verify), add:

```python
        from notifications.lane_feed import laneTap
        laneTap("orchestrator", f"phase: {phase_name}")
```

**`platform_core/orchestration/run_loop_mixin.py`** — at the top of the main run loop
iteration (where a subtask is selected/started), add:

```python
        from notifications.lane_feed import laneTap
        laneTap("orchestrator", f"loop: {getattr(subtask, 'subtask_id', '?')} {getattr(subtask, 'title', '')[:60]}")
```

**`agents/browser_executor.py`** — where a CDP action is dispatched (grep for the action
dispatch / `navigate` / `click`), guarded by the existing enable check:

```python
        from notifications.lane_feed import laneTap
        laneTap("browser", f"{action_name}: {str(action_arg)[:80]}")
```

**`agents/native_executor.py`** — at each UIA action dispatch:

```python
        from notifications.lane_feed import laneTap
        laneTap("native", f"{action_name}: {str(action_arg)[:80]}")
```

> Each tap is best-effort by construction (`laneTap` swallows errors). Keep imports
> local to the call site to avoid import cycles at module load.

- [ ] **Step 4: Run test + focused checks to verify they pass**

Run: `python -m pytest tests/test_terminal_taps.py -v`
Expected: PASS (2 passed).
Run: `python tools/dev.py check llm_io.py`
Expected: PASS (no size/import regressions).

- [ ] **Step 5: Commit**

```bash
git add llm_io.py platform_core/orchestration/run_loop_mixin.py platform_core/orchestration/run_phase_mixin.py agents/browser_executor.py agents/native_executor.py tests/test_terminal_taps.py
git commit -m "feat(taps): feed brain/orchestrator/browser/native into terminal lanes"
```

---

## Task 9: Start/stop the surface with the run

**Files:**
- Modify: the orchestrator path that constructs/starts `DiscordDashboard` (grep:
  `DiscordDashboard(` and `.set_tunnel_url` / dashboard `start`), and its teardown.

- [ ] **Step 1: Locate the dashboard lifecycle**

Run: `grep -rn "DiscordDashboard(" --include=*.py . | grep -v test | grep -v venv`
Note the file/function where the dashboard is created and where the run tears down.

- [ ] **Step 2: Start the surface alongside the dashboard**

Where the dashboard is created + started for a run, add:

```python
        from notifications.terminal_surface import TerminalSurface, set_terminal_surface
        _terminal = TerminalSurface()
        set_terminal_surface(_terminal)
        _terminal.start()
```

- [ ] **Step 3: Finalize the surface at run end**

In the same teardown that stops/finalizes the dashboard, add:

```python
        from notifications.terminal_surface import get_terminal_surface, set_terminal_surface
        _t = get_terminal_surface()
        if _t is not None:
            _t.finalize()
        set_terminal_surface(None)
```

- [ ] **Step 4: Verify import + focused orchestration tests**

Run: `python -c "import notifications.terminal_surface, notifications.views_terminal"`
Expected: exit 0.
Run: `python tools/dev.py fast`
Expected: PASS (broad Python suite green).

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "feat(orchestration): start/stop Live Terminal surface with the run"
```

---

## Task 10: Docs + repo map

**Files:**
- Modify: the closest observability doc under `docs/` (grep for the web-dashboard /
  `/api/raw` description); regenerate `AGENTS.md`.

- [ ] **Step 1: Document the surface**

Add a short "Live Terminal (Discord)" subsection to the observability doc: what it is,
the five lanes, the ◀/⏸/Raw/▶/📷 buttons, the adaptive-edit rate-limit behavior, and
that deep browser/native telemetry still lives on the web dashboard.

- [ ] **Step 2: Regenerate the module map**

Run: `python tools/repo_map.py`
Expected: `AGENTS.md` updated with the new modules.

- [ ] **Step 3: Size audit**

Run: `python tools/size_audit.py`
Expected: zero `must_split` violations.

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "docs(observability): document Discord Live Terminal + regen repo map"
```

---

## Task 11: Full verification

- [ ] **Step 1: Run the full fast suite**

Run: `python tools/dev.py fast`
Expected: PASS.

- [ ] **Step 2: Import smoke of the whole bot**

Run: `python -c "import notifications.command_bot; import notifications.bot.core; import notifications.terminal_surface; import notifications.views_terminal; print('ok')"`
Expected: `ok`.

- [ ] **Step 3: Confirm no size regressions**

Run: `python tools/size_audit.py`
Expected: zero `must_split`.

- [ ] **Step 4: Final commit (if anything pending)**

```bash
git add -A
git commit -m "chore: finalize Discord Live Terminal paginator" --allow-empty
```

---

## Self-Review Notes

- **Spec coverage:** lane bus (T1), lane taps/every-layer (T2,T8), pure renderer (T3),
  adaptive/backoff refresh (T4,T5), shared pinned message + snapshot (T5,T6),
  persistent view (T6,T7), start/stop lifecycle (T9), docs (T10). All spec §3 units and
  §10 files mapped.
- **Rate-limit math** lives in `EditThrottle` and is unit-tested independently of Discord.
- **Best-effort everywhere:** `laneTap`, `render`, `render_once`, `start`, `finalize`
  all swallow exceptions so no run path can break.
- **Facade contract verified** (Task 5 note): `discord_bot` re-exports
  `createMessage`/`editMessageResult`/`pinMessage`/`noticeEmbed`; edit returns
  `ok`/`not_found`/`transient`; buttons need `terminalControlRows()` on the REST payload.
- **Import-cycle avoided:** `TERM_CUSTOM_IDS` + `terminalControlRows()` live in the pure
  `terminal_render` module; both `terminal_surface` and `views_terminal` import from there,
  and `terminal_surface` never imports `views_terminal`.
- **Exact tap insertion points** located by grep in Task 8/9 (kept as local imports to
  avoid load-time cycles).
