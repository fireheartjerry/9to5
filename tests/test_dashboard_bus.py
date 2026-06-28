"""Tests for dashboard->bus routing, the tunnel pin, and cockpit codename/health richness."""
import config
from notifications import cv2
from notifications.dashboard import DiscordDashboard
from notifications.event_bus import get_bus, reset_bus


class _StubState:
    def __init__(self, meta, subtasks, data=None):
        self.meta = meta
        self.subtasks = subtasks
        self.data = data or {}
        self.task_id = "abcd1234efgh"


def _state(**over):
    meta = {"goal_raw": "Build the thing", "status": "executing", "control_mode": "watch",
            "started_at": None, "work_dir": "C:/9to5", "codename": "IRON_PHOENIX"}
    meta.update(over.get("meta", {}))
    subs = over.get("subtasks", [
        {"subtask_id": "st-001", "title": "first", "status": "done",
         "verify_result": {"passed": True, "cmd": "pytest"}},
    ])
    return _StubState(meta, subs, over.get("data", {"notifications": [], "adversary_reviews": []}))


def _flatten(comps):
    out = []

    def walk(n):
        if isinstance(n, dict):
            if n.get("type") == 10:
                out.append(str(n.get("content", "")))
            for v in n.values():
                walk(v)
        elif isinstance(n, list):
            for v in n:
                walk(v)

    walk(comps)
    return "\n".join(out)


def test_event_routes_to_bus(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_DASHBOARD", False)  # no network
    reset_bus()
    bus = get_bus()
    DiscordDashboard().event("subtask st-001 done")
    texts = [e["text"] for e in bus.history(last_n=10)]
    assert "subtask st-001 done" in texts


def test_set_tunnel_url_noop_when_disabled(monkeypatch):
    monkeypatch.setattr(config, "DISCORD_DASHBOARD", False)
    d = DiscordDashboard()
    d.set_tunnel_url("https://abc.trycloudflare.com")  # must not raise / no network
    assert d._tunnel_msg_id is None


def test_cockpit_has_codename_and_health():
    comps, _flags = cv2.buildCockpit(_state(), "executing")
    flat = _flatten(comps)
    assert "IRON_PHOENIX" in flat
    assert "Health" in flat


def test_cockpit_without_codename_still_renders():
    comps, _flags = cv2.buildCockpit(_state(meta={"codename": None}), "executing")
    flat = _flatten(comps)
    assert "9TO5" in flat
