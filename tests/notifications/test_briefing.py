"""Tests for the on-demand briefing generator (depth levels + preference tuning)."""
from notifications import briefing
from memory import user_prefs


class _State:
    def __init__(self):
        self.task_id = "abcd1234-0000"
        self.meta = {"goal_raw": "Fix the connection pool", "status": "executing",
                     "control_mode": "watch", "started_at": "2026-06-28T09:00:00",
                     "deadline_at": "2026-06-28T10:00:00", "codename": "IRON_PHOENIX",
                     "health_score": 87}
        self.subtasks = [
            {"subtask_id": "st-001", "title": "scaffold", "status": "done",
             "verify_result": {"passed": True}},
            {"subtask_id": "st-002", "title": "pool fix", "status": "done",
             "verify_result": {"passed": True}},
            {"subtask_id": "st-003", "title": "wire it", "status": "in_progress"},
        ]
        self.data = {"notifications": [{"at": "t", "kind": "subtask_done", "detail": "st-002"}],
                     "adversary_reviews": []}


def test_one_line_is_deterministic_and_single_line():
    out = briefing.generate_brief(_State(), user_prefs.DEFAULTS, depth="one-line")
    assert "\n" not in out.strip()
    assert "IRON_PHOENIX" in out
    assert "st-003" in out


def test_raw_returns_event_snapshot():
    out = briefing.generate_brief(_State(), user_prefs.DEFAULTS, depth="raw")
    assert "subtask_done" in out


def test_standard_uses_injected_chat():
    seen = {}

    def chat(system, user):
        seen["user"] = user
        return "IRON_PHOENIX is moving; st-003 active. ETA ~10min."

    out = briefing.generate_brief(_State(), user_prefs.DEFAULTS, depth="standard", chat=chat)
    assert "st-003" in out
    assert "IRON_PHOENIX" in seen["user"]  # context carried the codename


def test_standard_degrades_when_chat_offline():
    def boom(system, user):
        raise RuntimeError("ollama down")

    out = briefing.generate_brief(_State(), user_prefs.DEFAULTS, depth="standard", chat=boom)
    # falls back to the deterministic one-line so the operator always gets an answer
    assert "IRON_PHOENIX" in out


def test_deep_includes_subtask_breakdown():
    out = briefing.generate_brief(_State(), user_prefs.DEFAULTS, depth="deep",
                                  chat=lambda s, u: "synth")
    assert "st-001" in out and "st-002" in out and "st-003" in out


def test_default_depth_follows_prefs():
    prefs = dict(user_prefs.DEFAULTS, brief_default_depth="one-line")
    out = briefing.generate_brief(_State(), prefs, depth=None)
    assert "\n" not in out.strip()


def test_cost_pref_off_drops_cost_from_context():
    prefs = dict(user_prefs.DEFAULTS, brief_include_cost=False)
    seen = {}
    briefing.generate_brief(_State(), prefs, depth="standard",
                            chat=lambda s, u: seen.setdefault("u", u) or "ok")
    assert "cost" not in seen["u"].lower()
