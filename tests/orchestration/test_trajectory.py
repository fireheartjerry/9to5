# tests/test_trajectory.py
"""Tests for the eliza-style append-only JSONL trajectory recorder."""
import json

from platform_core.runtime import trajectory


def test_span_tree_parent_child(tmp_path):
    rec = trajectory.Recorder("run-abc", root=tmp_path)
    root_id = rec.openSpan("executor", None, {"sid": "st-001"})
    child_id = rec.openSpan("tool", root_id, {"tool": "Edit"})
    rec.closeSpan(child_id, usage={"input_tokens": 10}, cost_usd=0.0)
    rec.closeSpan(root_id, usage={"input_tokens": 50}, cost_usd=0.42)

    data = trajectory.loadSpans("run-abc", root=tmp_path)
    spans = {s["step_id"]: s for s in data["spans"]}
    assert spans[child_id]["parent_id"] == root_id
    assert spans[child_id]["kind"] == "tool"
    assert spans[root_id]["cost_usd"] == 0.42
    assert spans[child_id]["cost_usd"] == 0.0          # honest-zero for local Ollama
    assert spans[root_id]["usage"]["input_tokens"] == 50


def test_append_only_one_line_per_event(tmp_path):
    """O(1) per event: each open/close appends exactly ONE line -- no whole-file rewrite,
    no temp files, no fixed-temp-name race."""
    rec = trajectory.Recorder("run-x", root=tmp_path)
    sid = rec.openSpan("planner", None, {})
    rec.closeSpan(sid, usage=None, cost_usd=0.0)
    assert not list(tmp_path.glob("*.tmp"))
    lines = (tmp_path / "run-x.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2                             # one open + one close event
    assert json.loads(lines[0])["ev"] == "open"
    assert json.loads(lines[1])["ev"] == "close"


def test_replay_reconstructs_same_tree_old_writer_produced(tmp_path):
    """Property: replaying the JSONL yields the exact span dicts the recorder holds in
    memory (the shape the old whole-tree writer used to persist)."""
    rec = trajectory.Recorder("run-prop", root=tmp_path)
    a = rec.openSpan("executor", None, {"sid": "st-A"})
    b = rec.openSpan("tool", a, {"tool": "Bash"})
    c = rec.openSpan("verify", a, {})
    rec.closeSpan(b, usage={"input_tokens": 7}, cost_usd=0.01)
    rec.closeSpan(c, usage=None, cost_usd=0.0)
    rec.closeSpan(a, usage={"input_tokens": 99}, cost_usd=1.5)

    expected = {"run_id": "run-prop", "spans": [rec._spans[s] for s in rec._order]}
    assert trajectory.loadSpans("run-prop", root=tmp_path) == expected


def test_loader_accepts_legacy_whole_tree_json(tmp_path):
    """One-release compat: a pre-JSONL <run_id>.json span tree still loads."""
    legacy = {"run_id": "run-old", "spans": [
        {"step_id": "s1", "parent_id": None, "kind": "planner", "attrs": {},
         "opened_at": "2026-01-01T09:00:00+00:00", "closed_at": None,
         "usage": None, "cost_usd": None}]}
    (tmp_path / "run-old.json").write_text(json.dumps(legacy), encoding="utf-8")
    assert trajectory.loadSpans("run-old", root=tmp_path) == legacy


def test_torn_tail_line_skips_only_that_event(tmp_path):
    """A crash mid-append leaves a torn last line; the replay must keep every prior event."""
    rec = trajectory.Recorder("run-torn", root=tmp_path)
    sid = rec.openSpan("executor", None, {"sid": "st-1"})
    rec.closeSpan(sid, usage=None, cost_usd=0.0)
    with (tmp_path / "run-torn.jsonl").open("a", encoding="utf-8") as fh:
        fh.write('{"ev": "open", "step_id": "trunc')   # torn tail (no newline, invalid JSON)
    data = trajectory.loadSpans("run-torn", root=tmp_path)
    assert [s["step_id"] for s in data["spans"]] == [sid]
    assert data["spans"][0]["closed_at"] is not None


def test_every_method_is_exception_safe(tmp_path, monkeypatch):
    rec = trajectory.Recorder("run-e", root=tmp_path)
    sid = rec.openSpan("executor", None, {})

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(trajectory.jsonl_io, "appendRecord", _boom)
    # A write error must be swallowed -- no raise reaches the caller.
    rec.closeSpan(sid, usage=None, cost_usd=1.0)
    rec.openSpan("tool", sid, {})
