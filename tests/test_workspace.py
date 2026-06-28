"""Tests for human_nature.workspace — Global Workspace (GWT).

All tests are pure/offline: specialists are plain callables; no Ollama, no Discord.
"""
from __future__ import annotations


def _make_specialist(content: str, salience: float):
    """Return a minimal specialist callable."""
    def specialist(state):
        return {"content": content, "salience": salience}
    return specialist


# ---------------------------------------------------------------------------
# tick() — competition and winner selection
# ---------------------------------------------------------------------------

def test_highest_salience_wins():
    from human_nature.workspace import Workspace

    ws = Workspace()
    ws.register("low", _make_specialist("boring", 0.2))
    ws.register("high", _make_specialist("exciting", 0.9))
    result = ws.tick(state={})
    assert result is not None
    assert result["winner"] == "high"
    assert result["content"] == "exciting"
    assert result["salience"] == 0.9


def test_losers_listed():
    from human_nature.workspace import Workspace

    ws = Workspace()
    ws.register("alpha", _make_specialist("a", 0.3))
    ws.register("beta", _make_specialist("b", 0.8))
    ws.register("gamma", _make_specialist("c", 0.1))
    result = ws.tick(state={})
    assert result["winner"] == "beta"
    assert set(result["losers"]) == {"alpha", "gamma"}


def test_tie_broken_by_registration_order():
    from human_nature.workspace import Workspace

    ws = Workspace()
    ws.register("first", _make_specialist("first-content", 0.7))
    ws.register("second", _make_specialist("second-content", 0.7))
    result = ws.tick(state={})
    assert result["winner"] == "first"
    assert "second" in result["losers"]


def test_empty_registry_returns_none():
    from human_nature.workspace import Workspace

    ws = Workspace()
    assert ws.tick(state={}) is None


def test_single_specialist_wins_with_no_losers():
    from human_nature.workspace import Workspace

    ws = Workspace()
    ws.register("solo", _make_specialist("alone", 0.5))
    result = ws.tick(state={})
    assert result["winner"] == "solo"
    assert result["losers"] == []


# ---------------------------------------------------------------------------
# broadcast() — optional on_broadcast callback
# ---------------------------------------------------------------------------

def test_broadcast_calls_on_broadcast_when_present():
    from human_nature.workspace import Workspace

    received = []

    class ObservingSpecialist:
        def __call__(self, state):
            return {"content": "obs", "salience": 0.4}

        def on_broadcast(self, winner):
            received.append(winner)

    ws = Workspace()
    ws.register("observer", ObservingSpecialist())
    winner = {"winner": "other", "content": "x", "salience": 0.9, "losers": ["observer"]}
    ws.broadcast(winner)
    assert received == [winner]


def test_broadcast_does_not_crash_on_specialist_without_on_broadcast():
    from human_nature.workspace import Workspace

    ws = Workspace()
    ws.register("dumb", _make_specialist("plain", 0.5))
    winner = {"winner": "dumb", "content": "plain", "salience": 0.5, "losers": []}
    # Must not raise
    ws.broadcast(winner)


def test_broadcast_calls_all_with_on_broadcast():
    from human_nature.workspace import Workspace

    log = []

    def make_observer(name):
        class Obs:
            def __call__(self, state):
                return {"content": name, "salience": 0.1}
            def on_broadcast(self, winner):
                log.append(name)
        return Obs()

    ws = Workspace()
    ws.register("obs_a", make_observer("a"))
    ws.register("obs_b", make_observer("b"))
    ws.register("dumb", _make_specialist("dumb", 0.3))  # no on_broadcast

    ws.broadcast({"winner": "dumb", "content": "dumb", "salience": 0.3, "losers": ["obs_a", "obs_b"]})
    assert set(log) == {"a", "b"}


def test_broadcast_isolates_failing_on_broadcast():
    from human_nature.workspace import Workspace
    log = []
    class Crasher:
        def __call__(self, state): return {"content": "c", "salience": 0.1}
        def on_broadcast(self, winner): raise RuntimeError("boom")
    class Recorder:
        def __call__(self, state): return {"content": "r", "salience": 0.1}
        def on_broadcast(self, winner): log.append(winner)
    ws = Workspace()
    ws.register("crash", Crasher())
    ws.register("record", Recorder())
    ws.broadcast({"winner": "x", "content": "x", "salience": 0.9, "losers": []})
    assert len(log) == 1  # Recorder still notified despite Crasher raising


def test_three_way_tie_first_registered_wins():
    from human_nature.workspace import Workspace
    ws = Workspace()
    ws.register("a", lambda s: {"content": "A", "salience": 0.5})
    ws.register("b", lambda s: {"content": "B", "salience": 0.5})
    ws.register("c", lambda s: {"content": "C", "salience": 0.5})
    result = ws.tick({})
    assert result["winner"] == "a"
