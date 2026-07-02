"""Tests for the LiveEventBus nervous system (rings, SSE pub/sub, singleton)."""
from notifications.event_bus import Event, LiveEventBus, get_bus, reset_bus


def test_emit_and_history():
    bus = LiveEventBus()
    bus.emit(Event(kind="tool_use", sid="st-001", text="editing x.py"))
    h = bus.history(last_n=10)
    assert h[-1]["kind"] == "tool_use"
    assert h[-1]["text"] == "editing x.py"
    assert "at" in h[-1]  # wall-clock label for the UI


def test_raw_ring_per_sid():
    bus = LiveEventBus()
    for i in range(5):
        bus.emit_raw("st-001", f"line {i}")
    bus.emit_raw("st-002", "other")
    rh = bus.raw_history("st-001", last_n=10)
    assert [r["line"] for r in rh] == [f"line {i}" for i in range(5)]
    assert bus.raw_history("st-002")[-1]["line"] == "other"


def test_sse_subscribe_receives_events():
    bus = LiveEventBus()
    q = bus.subscribe_sse()
    assert bus.sse_subscriber_count() == 1
    bus.emit(Event(kind="phase", sid="system", text="executing"))
    item = q.get_nowait()
    assert item["kind"] == "phase"
    bus.unsubscribe_sse(q)
    assert bus.sse_subscriber_count() == 0


def test_history_filter_by_sid():
    bus = LiveEventBus()
    bus.emit(Event(kind="tool_use", sid="st-001", text="a"))
    bus.emit(Event(kind="tool_use", sid="st-002", text="b"))
    filtered = bus.history(sid="st-002")
    assert filtered and all(e["sid"] == "st-002" for e in filtered)


def test_history_last_n():
    bus = LiveEventBus()
    for i in range(10):
        bus.emit(Event(kind="raw", sid="s", text=str(i)))
    assert len(bus.history(last_n=3)) == 3


def test_singleton_and_reset():
    reset_bus()
    a = get_bus()
    b = get_bus()
    assert a is b
    reset_bus()
    assert get_bus() is not a


def test_full_subscriber_queue_never_blocks():
    bus = LiveEventBus()
    bus.subscribe_sse()  # never drained
    for i in range(5000):
        bus.emit(Event(kind="raw", sid="s", text=str(i)))  # must not hang


def test_raw_ring_capacity():
    bus = LiveEventBus()
    # per-sid ring keeps last 1000; structured/raw rings keep more.
    for i in range(1200):
        bus.emit_raw("st-001", str(i))
    rh = bus.raw_history("st-001", last_n=5000)
    assert len(rh) == 1000
    assert rh[-1]["line"] == "1199"
