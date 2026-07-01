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
