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
