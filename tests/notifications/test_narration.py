"""Tests for proactive narration, moments, and attention-mode detection."""
from notifications.event_bus import LiveEventBus
from notifications.narration import Narrator, detect_mode, emit_moment


def test_rate_limit():
    t = {"v": 0.0}
    n = Narrator(min_interval=60.0, clock=lambda: t["v"])
    sent = []
    n._sink = lambda text, role: (sent.append(text), True)[1]
    assert n.narrate("a") is True
    assert n.narrate("b") is False        # within 60s of the last post
    t["v"] = 61.0
    assert n.narrate("c") is True
    assert sent == ["a", "c"]


def test_force_bypasses_rate_limit():
    t = {"v": 0.0}
    n = Narrator(min_interval=60.0, clock=lambda: t["v"])
    n._sink = lambda text, role: True
    assert n.narrate("a") is True
    assert n.narrate("b", force=True) is True   # forced through despite the window


def test_detect_mode():
    bus = LiveEventBus()
    assert detect_mode(bus) == "away"
    bus.subscribe_sse()
    assert detect_mode(bus) == "present"


def test_emit_moment_posts_to_bus():
    bus = LiveEventBus()
    posted = []
    emit_moment(bus, "st-002", "Claude found something the subtask didn't ask for.",
                sink=lambda text, role: posted.append(text) or True)
    evt = [e for e in bus.history(last_n=10) if e["kind"] == "moment"]
    assert evt and "found something" in evt[-1]["text"]
    assert posted  # also narrated to the channel


def test_narrate_never_raises_on_bad_sink():
    n = Narrator(min_interval=0.0)
    n._sink = lambda text, role: (_ for _ in ()).throw(RuntimeError("boom"))
    assert n.narrate("x") is False  # swallowed
