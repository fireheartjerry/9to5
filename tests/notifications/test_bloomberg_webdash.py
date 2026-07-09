"""Tests for the Bloomberg web dashboard page + payload builders + enriched snapshot."""
import config
from notifications import webdash
from notifications.event_bus import get_bus, reset_bus


def test_page_is_bloomberg():
    p = webdash._PAGE
    for token in ("#000000", "#ff9f00", "#00d4aa", "#ff4444", "EventSource",
                  "ui-monospace", "EXPAND RAW STDOUT", "INTELLIGENCE CURVE", "/api/events",
                  "/api/raw", "/api/council", "PRE-EXECUTION COUNCIL"):
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
    for k in ("health", "arc", "wisdom_trail", "intelligence_curve", "comparative", "council",
              "model", "replans", "adversary", "discovery"):
        assert k in snap, k
    assert snap["health"]["score"] == 100
    assert snap["health"]["color"] == "#00d4aa"
    assert snap["tunnel_url"] == "https://abc.trycloudflare.com"
    assert snap["meta"]["task_id"] == state.task_id
    assert snap["council"]["status"] == "not_run"


def test_council_transcript_endpoint_payload(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "tasks")
    monkeypatch.setattr(config, "PROJECT_ROOT", tmp_path)
    from state.task import TaskState
    transcript_dir = tmp_path / "state" / "council_runs" / "run"
    transcript_dir.mkdir(parents=True)
    transcript = transcript_dir / "transcript.md"
    transcript.write_text("GPT: hello\nCerebras: sharp critique\n", encoding="utf-8")
    state = TaskState.create("show council transcript", 1.0)
    state.meta["pre_execution_council"] = {
        "status": "completed",
        "run_id": "run-123456",
        "provider_health": ["GPT: live", "Cerebras: live"],
        "transcript_path": str(transcript),
    }
    state.save()

    snap = webdash._snapshot(state.task_id)
    payload = webdash.read_transcript(state)

    assert snap["council"]["transcript_available"] is True
    assert "Cerebras: live" in snap["council"]["provider_health"]
    assert payload["ok"] is True
    assert "Cerebras: sharp critique" in payload["content"]


def test_snapshot_missing_task_is_empty(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    assert webdash._snapshot("does-not-exist") == {"empty": True}


def test_snapshot_caches_derived_metrics(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(config, "WEBDASH_DERIVED_TTL_SECONDS", 60, raising=False)
    webdash._DERIVED_CACHE.clear()
    calls = {"wisdom": 0, "curve": 0, "comparative": 0}

    def wisdom(goal):  # noqa: ANN001
        calls["wisdom"] += 1
        return [{"summary": goal, "run": "abc"}]

    def curve():
        calls["curve"] += 1
        return [{"domain": "tests", "pct": 100}]

    def comparative(task_id):  # noqa: ANN001
        calls["comparative"] += 1
        return {"pace": 1, "innovation": 1, "adversary": 0, "replans": 0}

    monkeypatch.setattr(webdash, "_wisdom_trail", wisdom)
    monkeypatch.setattr(webdash, "_intelligence_curve", curve)
    monkeypatch.setattr(webdash, "_comparative", comparative)

    from state.task import TaskState
    state = TaskState.create("cache dashboard widgets", 1.0)
    state.save()

    first = webdash._snapshot(state.task_id)
    second = webdash._snapshot(state.task_id)

    assert first["wisdom_trail"] == second["wisdom_trail"]
    assert calls == {"wisdom": 1, "curve": 1, "comparative": 1}
