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
