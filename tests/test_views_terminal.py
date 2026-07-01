from notifications.terminal_render import TERM_CUSTOM_IDS
from notifications.views_terminal import TerminalView


def test_view_is_persistent_and_matches_shared_ids():
    v = TerminalView()
    assert v.timeout is None
    ids = {c.custom_id for c in v.children if hasattr(c, "custom_id")}
    assert set(TERM_CUSTOM_IDS.values()) <= ids   # ids come from terminal_render (single source)
