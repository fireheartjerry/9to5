"""Epic 5 wire-type TypedDicts are importable and structurally usable."""
from platform_core.core.contracts import BlackboardEntry, WorkerMessage, DebateVerdict


def test_blackboard_entry_shape():
    e: BlackboardEntry = {
        "entry_id": "bb-1", "key": "result:st-007", "kind": "result",
        "author": "coder", "to": "coordinator", "subtask_id": "st-007",
        "value": {"ok": True}, "refs": [], "span_id": None, "ts_ns": 1,
    }
    assert e["kind"] == "result"


def test_worker_message_shape():
    m: WorkerMessage = {"role": "coder", "subtask_id": "st-007",
                        "kind": "result", "ok": True, "summary": "done",
                        "refs": [], "value": {}}
    assert m["ok"] is True


def test_debate_verdict_shape():
    v: DebateVerdict = {"resolved": True, "winner": "coder",
                        "reason": "consensus", "rounds": 1,
                        "stopped_reason": "consensus"}
    assert v["stopped_reason"] == "consensus"
