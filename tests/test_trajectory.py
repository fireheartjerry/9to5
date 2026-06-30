# tests/test_trajectory.py
"""Tests for the eliza-style file span-tree trajectory recorder."""
import json

from platform_core.runtime import trajectory


def test_span_tree_parent_child(tmp_path):
    rec = trajectory.Recorder("run-abc", root=tmp_path)
    root_id = rec.openSpan("executor", None, {"sid": "st-001"})
    child_id = rec.openSpan("tool", root_id, {"tool": "Edit"})
    rec.closeSpan(child_id, usage={"input_tokens": 10}, cost_usd=0.0)
    rec.closeSpan(root_id, usage={"input_tokens": 50}, cost_usd=0.42)

    data = json.loads((tmp_path / "run-abc.json").read_text(encoding="utf-8"))
    spans = {s["step_id"]: s for s in data["spans"]}
    assert spans[child_id]["parent_id"] == root_id
    assert spans[child_id]["kind"] == "tool"
    assert spans[root_id]["cost_usd"] == 0.42
    assert spans[child_id]["cost_usd"] == 0.0          # honest-zero for local Ollama
    assert spans[root_id]["usage"]["input_tokens"] == 50


def test_atomic_write_leaves_no_partial(tmp_path):
    rec = trajectory.Recorder("run-x", root=tmp_path)
    rec.openSpan("planner", None, {})
    # No *.tmp partial left behind after an atomic tmp+rename write.
    assert not list(tmp_path.glob("*.tmp"))
    assert (tmp_path / "run-x.json").exists()


def test_every_method_is_exception_safe(tmp_path, monkeypatch):
    rec = trajectory.Recorder("run-e", root=tmp_path)
    sid = rec.openSpan("executor", None, {})

    def _boom(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(trajectory.os, "replace", _boom)
    # A write error must be swallowed -- no raise reaches the caller.
    rec.closeSpan(sid, usage=None, cost_usd=1.0)
    rec.openSpan("tool", sid, {})
