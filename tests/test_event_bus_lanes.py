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
