"""Tests for the Bloomberg web dashboard page + payload builders + enriched snapshot."""
import config
from notifications import webdash
from notifications.event_bus import get_bus, reset_bus


def test_page_is_bloomberg():
    p = webdash._PAGE
    for token in ("#000000", "#ff9f00", "#00d4aa", "#ff4444", "EventSource",
                  "ui-monospace", "EXPAND RAW STDOUT", "INTELLIGENCE CURVE", "/api/events",
                  "/api/raw"):
        assert token in p, token


def test_page_keeps_control_token_placeholder():
    assert "__WEBDASH_TOKEN__" in webdash._PAGE


def test_raw_payload_reads_bus():
    reset_bus()
    bus = get_bus()
    bus.emit_raw("st-001", "hello world")
    payload = webdash._raw_payload("st-001")
    assert "hello world" in payload
    assert webdash._raw_payload("nope") == "[]"


def test_snapshot_has_surface_keys(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    from state.task import TaskState
    state = TaskState.create("harden the rate-limit path", 2.0)
    state.meta["status"] = "executing"
    state.meta["tunnel_url"] = "https://abc.trycloudflare.com"
    state.addSubtask("first thing", "do it")
    state.save()
    snap = webdash._snapshot(state.task_id)
    for k in ("codename", "tunnel_url"):
        assert k in snap["meta"]
    for k in ("health", "arc", "wisdom_trail", "intelligence_curve", "comparative",
              "model", "replans", "adversary", "discovery"):
        assert k in snap, k
    assert snap["health"]["score"] == 100
    assert snap["health"]["color"] == "#00d4aa"
    assert snap["tunnel_url"] == "https://abc.trycloudflare.com"
    assert snap["meta"]["task_id"] == state.task_id


def test_snapshot_missing_task_is_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    assert webdash._snapshot("does-not-exist") == {"empty": True}
