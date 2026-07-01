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
