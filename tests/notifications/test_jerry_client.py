"""notifications/jerry_client.py -- the shadow-mode bridge to the Jerry decision service.

Previously unmapped (no test at all). Covers buildGateContext's TaskState summarization
(happy path + best_effort degrade-on-crash), decide()'s HTTP round-trip (service verb,
service says "none", service unreachable), advise()'s formatting, and recordOutcome's
shadow-log JSONL write -- all offline (urlopen mocked, SHADOW_LOG redirected to tmp_path).
"""

from __future__ import annotations

import json
from unittest import mock

from notifications import jerry_client


class _FakeState:
    def __init__(self, *, meta=None, subtasks=None, data=None):
        self.meta = meta or {}
        self.subtasks = subtasks if subtasks is not None else []
        self.data = data or {}


def test_build_gate_context_summarizes_progress_and_current_subtask():
    state = _FakeState(
        meta={"goal_raw": "ship the thing", "status": "running"},
        subtasks=[
            {"subtask_id": "st-1", "status": "done", "title": "setup", "verify_result": {"passed": True}},
            {
                "subtask_id": "st-2",
                "status": "in_progress",
                "title": "build",
                "verify_result": {"passed": False, "summary": "flaky test"},
            },
            {"subtask_id": "st-3", "status": "pending", "title": "ship"},
            {"subtask_id": "st-4", "status": "removed", "title": "dead"},
        ],
        data={"notifications": [{"kind": "info", "text": "started"}]},
    )

    ctx = jerry_client.buildGateContext("execute", state)

    assert ctx["goal"] == "ship the thing"
    assert ctx["status"] == "running"
    assert ctx["progress"] == "1/3"  # removed subtask excluded from total
    assert ctx["current"] == "st-2 build"
    assert any("flaky test" in e for e in ctx["errors"])
    assert any("started" in e for e in ctx["events"])


def test_build_gate_context_degrades_to_default_on_crash():
    class _BrokenState:
        @property
        def meta(self):
            raise RuntimeError("boom")

    ctx = jerry_client.buildGateContext("execute", _BrokenState())

    assert ctx == {
        "goal": "",
        "status": "?",
        "progress": "?",
        "current": "",
        "subtasks": [],
        "events": [],
        "errors": [],
    }


def _fake_response(payload: dict):
    body = json.dumps(payload).encode("utf-8")
    resp = mock.MagicMock()
    resp.read.return_value = body
    resp.__enter__.return_value = resp
    resp.__exit__.return_value = False
    return resp


def test_decide_returns_verb_dict_when_service_predicts():
    state = _FakeState()
    with mock.patch(
        "notifications.jerry_client.urllib.request.urlopen",
        return_value=_fake_response({"verb": "approve", "confidence": 0.9}),
    ):
        out = jerry_client.decide("execute", state)
    assert out == {"verb": "approve", "confidence": 0.9}


def test_decide_returns_none_when_service_says_none():
    state = _FakeState()
    with mock.patch(
        "notifications.jerry_client.urllib.request.urlopen", return_value=_fake_response({"verb": "none"})
    ):
        out = jerry_client.decide("execute", state)
    assert out is None


def test_decide_returns_none_when_service_unreachable():
    state = _FakeState()
    with mock.patch(
        "notifications.jerry_client.urllib.request.urlopen", side_effect=OSError("connection refused")
    ):
        out = jerry_client.decide("execute", state)
    assert out is None


def test_advise_formats_one_line_second_opinion():
    state = _FakeState()
    with mock.patch(
        "notifications.jerry_client.decide",
        return_value={"verb": "approve", "confidence": 0.8, "message": "looks good"},
    ):
        line = jerry_client.advise("execute", state)
    assert line == "would lean 'approve' (confidence 0.8): looks good"


def test_advise_returns_none_when_decide_returns_none():
    state = _FakeState()
    with mock.patch("notifications.jerry_client.decide", return_value=None):
        assert jerry_client.advise("execute", state) is None


def test_record_outcome_appends_shadow_log_line(tmp_path, monkeypatch):
    log_path = tmp_path / "jerry_shadow.jsonl"
    monkeypatch.setattr(jerry_client, "SHADOW_LOG", log_path)

    jerry_client.recordOutcome("execute", {"verb": "approve", "confidence": 0.7}, "approve")

    lines = log_path.read_text(encoding="utf-8").strip().splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["gate"] == "execute"
    assert rec["model_verb"] == "approve"
    assert rec["human_verb"] == "approve"
    assert rec["agreed"] is True


def test_record_outcome_never_raises_on_write_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(jerry_client, "SHADOW_LOG", tmp_path / "no" / "such" / "dir" / "x.jsonl")
    with mock.patch.object(jerry_client.Path, "mkdir", side_effect=OSError("disk full")):
        jerry_client.recordOutcome("execute", None, "reject")  # must not raise
