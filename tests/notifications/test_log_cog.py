"""log_cog gateway shell: command surface + bang-dispatch routing (no live gateway)."""
from notifications.bot.cogs import log_cog


def test_cog_exposes_expected_slash_commands():
    attrs = dir(log_cog.LogCog)
    for cmd in ("brief", "why", "explain", "wisdom", "growth", "intent", "prefer", "prefs"):
        assert cmd in attrs


def test_setup_is_callable():
    assert callable(log_cog.setup)


def test_bang_dispatch_routes_brief(monkeypatch):
    seen = {}

    def fake_brief(state, prefs, depth, chat=None):
        seen["d"] = depth
        return "BRIEF"

    monkeypatch.setattr(log_cog.briefing, "generate_brief", fake_brief)
    out = log_cog.dispatchBang("!brief one-line", state=object(), prefs={})
    assert out == "BRIEF" and seen["d"] == "one-line"


def test_bang_dispatch_routes_why(monkeypatch):
    monkeypatch.setattr(log_cog.brain_dialogue, "answer",
                        lambda kind, arg, state, chat=None: f"{kind}:{arg}")
    out = log_cog.dispatchBang("!why st-004 before st-005", state=object(), prefs={})
    assert out.startswith("why:")


def test_bang_dispatch_routes_wisdom(monkeypatch):
    monkeypatch.setattr(log_cog.wisdom, "wisdomTrail", lambda state, **k: "WISDOM")
    assert log_cog.dispatchBang("!wisdom", state=object(), prefs={}) == "WISDOM"


def test_bang_dispatch_brief_set_routes_prefs(monkeypatch):
    out = log_cog.dispatchBang("!brief set cost off", state=object(), prefs={})
    assert "cost" in out.lower()


def test_bang_dispatch_ignores_non_bang():
    assert log_cog.dispatchBang("hello", state=object(), prefs={}) is None


def test_bang_dispatch_ignores_unknown_bang():
    assert log_cog.dispatchBang("!status", state=object(), prefs={}) is None
